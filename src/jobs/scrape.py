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


def run_cycle(config: Config, db: Database, api: TelegramApi, *, fetch=collect_all) -> dict:
    """Один полный прогон. Возвращает счётчики для логов/тестов."""
    listings = fetch()
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
    }
    logger.info(
        "Прогон завершён: найдено=%(found)d, новых=%(new)d, в очередь=%(queued)d, "
        "отправлено=%(sent)d, даунгрейдов=%(downgraded)d, напоминаний=%(reminded)d",
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
