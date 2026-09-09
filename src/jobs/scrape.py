"""Цикл парсинга и рассылки: python -m src.jobs.scrape

Поток одного прогона:
    1. Все парсеры (комнаты + квартиры, вся Беларусь) -> список Listing.
    2. Вставка в listings (дубликаты игнорируются) -> реально новые.
    3. Матчинг новых по активным фильтрам юзеров -> очередь deliveries.
    4. Отправка назревших доставок (премиум сразу, free батчем).
    5. Обслуживание подписок: даунгрейд просроченных, напоминания.
    6. Очистка старых объявлений (старше CLEANUP_DAYS).

Запускается GitHub Actions (scrape.yml) каждые 2–3 минуты.
"""

from __future__ import annotations

from src import delivery, tariffs
from src.bot import texts
from src.config import Config, load_config
from src.db import Database, SupabaseDatabase
from src.http_client import HttpClient
from src.logging_setup import get_logger
from src.matching import build_deliveries
from src.models import Listing
from src.parsers.base import BaseParser
from src.parsers.kufar import KufarApartmentsParser, KufarRoomsParser
from src.parsers.onliner import OnlinerApartmentsParser, OnlinerRoomsParser
from src.parsers.realt import RealtApartmentsParser, RealtRoomsParser
from src.telegram import TelegramApi

logger = get_logger(__name__)

# Реестр активных парсеров. Добавляйте сюда классы новых сайтов.
# Шаблон нового парсера: src/parsers/example_site.py
PARSER_CLASSES: list[type[BaseParser]] = [
    KufarRoomsParser,
    KufarApartmentsParser,
    RealtRoomsParser,
    RealtApartmentsParser,
    OnlinerRoomsParser,
    OnlinerApartmentsParser,
]

# Объявления старше этого срока удаляются из БД (deliveries — каскадом).
CLEANUP_DAYS = 30

# Префикс ключа в bot_state, где хранится улов парсера за прошлый прогон.
PARSER_COUNT_KEY = "parser_count:"

# С какого улова падение до нуля считается поломкой, а не естественным
# колебанием ленты. realt_rooms отдаёт 0-1 объявление по всей стране, и его
# ноль ничего не значит; ноль после полусотни — значит.
MIN_VOLUME_FOR_ALERT = 5


def collect_listings(parsers: list[BaseParser]) -> list[Listing]:
    """Собрать объявления со всех парсеров. Ошибка одного не валит остальные."""
    all_listings: list[Listing] = []
    for parser in parsers:
        try:
            items = parser.fetch()
            logger.info("[%s] получено объявлений: %d", parser.name, len(items))
            all_listings.extend(items)
        except Exception as exc:  # noqa: BLE001 — намеренно изолируем любой парсер
            logger.error("[%s] парсер упал: %s", parser.name, exc, exc_info=True)
    return all_listings


def collect_all() -> list[Listing]:
    """Загрузить объявления со всех сайтов (общий HTTP-клиент на прогон)."""
    with HttpClient() as client:
        parsers = [cls(client=client) for cls in PARSER_CLASSES]
        return collect_listings(parsers)


def count_by_source(listings: list[Listing]) -> dict[str, int]:
    """Сколько объявлений отдал каждый парсер за прогон.

    Считаем от реестра, а не от результата: упавший или замолчавший парсер
    в listings вообще не представлен, но в счётчиках обязан быть нулём.
    """
    counts = {cls.name: 0 for cls in PARSER_CLASSES}
    for listing in listings:
        if listing.source in counts:
            counts[listing.source] += 1
    return counts


def alert_parser_health(db: Database, api: TelegramApi, config: Config,
                        counts: dict[str, int]) -> int:
    """Сообщить админу, если парсер замолчал (или снова заговорил).

    Сравниваем улов с прошлым прогоном (bot_state). Тревога — на переходе
    «была заметная лента -> стало ноль»: сайт сменил разметку, закрыл доступ
    или парсер упал. Иначе бот молча перестаёт рассылать, а зелёный workflow
    это не показывает.

    «Заметная» — не меньше MIN_VOLUME_FOR_ALERT. Малообъёмные ленты честно
    колеблются около нуля: у realt_rooms по всей Беларуси одна свежая комната,
    она выходит за MAX_AGE_DAYS и счётчик падает в 0 без всякой поломки.
    Тревожиться на такое — значит приучить админа игнорировать алерты.

    Повторно об одном и том же не пишем: после алерта в state лежит 0, и
    следующий нулевой прогон уже не тревога. Возвращает число отправленных
    уведомлений.
    """
    admin_chat_id = config.admin_chat_id
    alerts = 0
    for name, count in counts.items():
        key = f"{PARSER_COUNT_KEY}{name}"
        raw_previous = db.get_state(key)
        try:
            previous = int(raw_previous) if raw_previous is not None else None
        except ValueError:
            logger.warning("Не разобрал %s=%r — считаю отсутствующим", key, raw_previous)
            previous = None

        if previous is not None and previous >= MIN_VOLUME_FOR_ALERT and count == 0:
            logger.error("[%s] парсер замолчал: было %d, стало 0", name, previous)
            if admin_chat_id and api is not None:
                api.send_message(admin_chat_id, texts.fmt_admin_parser_silent(name, previous))
                alerts += 1
        elif previous == 0 and count >= MIN_VOLUME_FOR_ALERT:
            # О восстановлении пишем только тем, о чьей поломке сообщали:
            # порог тот же, иначе алерт «ожил» пришёл бы без парного «замолчал».
            logger.info("[%s] парсер ожил: %d объявлений", name, count)
            if admin_chat_id and api is not None:
                api.send_message(admin_chat_id, texts.fmt_admin_parser_recovered(name, count))
                alerts += 1
        elif count == 0 and previous is not None and previous > 0:
            logger.info(
                "[%s] улов упал до нуля, но лента малообъёмная (было %d < %d) — не тревога",
                name, previous, MIN_VOLUME_FOR_ALERT,
            )

        # Пишем только при изменении — иначе лишний UPDATE каждые 2 минуты.
        if previous != count:
            db.set_state(key, str(count))
    return alerts


def run_cycle(config: Config, db: Database, api: TelegramApi, *, fetch=collect_all) -> dict:
    """Один полный прогон. Возвращает счётчики для логов/тестов."""
    listings = fetch()
    alerts = alert_parser_health(db, api, config, count_by_source(listings))
    rows = [l.to_db_row() for l in listings]
    new_rows = db.insert_new_listings(rows)

    pairs = build_deliveries(new_rows, db.get_active_filters_with_users())
    queued = db.queue_deliveries(pairs)
    sent = delivery.send_pending(db, api, config)

    downgraded = tariffs.downgrade_expired(db, api)
    reminded = tariffs.remind_expiring(db, api)
    db.cleanup_old_rows(CLEANUP_DAYS)

    stats = {
        "found": len(listings),
        "new": len(new_rows),
        "queued": queued,
        "sent": sent,
        "downgraded": downgraded,
        "reminded": reminded,
        "alerts": alerts,
    }
    logger.info(
        "Прогон завершён: найдено=%(found)d, новых=%(new)d, в очередь=%(queued)d, "
        "отправлено=%(sent)d, даунгрейдов=%(downgraded)d, напоминаний=%(reminded)d, "
        "алертов=%(alerts)d",
        stats,
    )
    return stats


def main() -> None:
    config = load_config(require_telegram=False, require_bot=True)
    db = SupabaseDatabase(config.supabase_url, config.supabase_service_key)
    try:
        with TelegramApi(config.telegram_bot_token) as api:
            run_cycle(config, db, api)
    except Exception as exc:  # noqa: BLE001 — верхний уровень: лог и код 1
        logger.error("Фатальная ошибка scrape: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
