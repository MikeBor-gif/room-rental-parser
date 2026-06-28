"""Оркестратор: запуск всех парсеров, дедупликация, отправка в Telegram.

Запуск:
    python -m src.main

Поток:
    1. Загрузить конфиг (токен, chat_id, фильтры).
    2. Для каждого парсера вызвать fetch() (падение одного не валит остальные).
    3. Применить фильтры (цена, ключевые слова).
    4. Отфильтровать новые (которых нет в SeenStore).
    5. Отправить новые в Telegram.
    6. Пометить отправленные как виденные.
"""

from __future__ import annotations

import time

from src.config import Config, load_config
from src.http_client import HttpClient
from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser
from src.parsers.kufar_rooms import KufarRoomsParser
from src.storage import SeenStore
from src.telegram import TelegramNotifier

logger = get_logger(__name__)

# Реестр активных парсеров. Добавляйте сюда классы новых сайтов.
# Шаблон нового парсера: src/parsers/example_site.py
PARSER_CLASSES: list[type[BaseParser]] = [
    KufarRoomsParser,
]


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


def apply_filters(listings: list[Listing], config: Config) -> list[Listing]:
    """Отфильтровать по цене и ключевым словам из конфига."""
    result: list[Listing] = []
    for listing in listings:
        if config.max_price is not None and listing.price_value is not None:
            if listing.price_value > config.max_price:
                logger.debug("Фильтр цены отсёк: %s (%.0f)", listing.id, listing.price_value)
                continue
        if config.keywords:
            haystack = f"{listing.title} {listing.location or ''}".lower()
            if not any(kw in haystack for kw in config.keywords):
                logger.debug("Фильтр ключевых слов отсёк: %s", listing.id)
                continue
        result.append(listing)
    logger.debug("После фильтров осталось %d из %d", len(result), len(listings))
    return result


def select_new(listings: list[Listing], store: SeenStore) -> list[Listing]:
    """Оставить только объявления, которых ещё нет в хранилище."""
    new_items = [l for l in listings if not store.is_seen(l.id)]
    logger.debug("Новых объявлений: %d из %d", len(new_items), len(listings))
    return new_items


def run(config: Config | None = None) -> int:
    """Выполнить один полный цикл. Возвращает число отправленных объявлений."""
    config = config or load_config(require_telegram=True)
    logger.info("Запуск цикла парсинга (%d парсеров)", len(PARSER_CLASSES))

    with HttpClient() as client:
        parsers = [cls(client=client) for cls in PARSER_CLASSES]
        listings = collect_listings(parsers)

    filtered = apply_filters(listings, config)

    sent = 0
    with SeenStore(config.db_path) as store:
        new_items = select_new(filtered, store)
        if not new_items:
            logger.info("Новых объявлений нет — уведомления не отправляются")
            return 0

        with TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id) as notifier:
            for listing in new_items:
                if notifier.send_listing(listing):
                    store.mark_seen(listing.id, source=listing.source)
                    sent += 1

    logger.info(
        "Цикл завершён: найдено=%d, после фильтров=%d, новых=%d, отправлено=%d",
        len(listings),
        len(filtered),
        len(new_items),
        sent,
    )
    return sent


def run_forever(
    config: Config,
    *,
    max_iterations: int | None = None,
    sleep=time.sleep,
) -> int:
    """Режим демона: бесконечный цикл с паузой config.poll_interval между прогонами.

    Ошибка одного прогона не останавливает сервис — логируется и цикл продолжается.
    Параметр max_iterations нужен для тестов (ограничить число итераций).
    Возвращает число выполненных итераций.
    """
    logger.info("Режим демона: интервал опроса %d c", config.poll_interval)
    iteration = 0
    while True:
        iteration += 1
        try:
            run(config)
        except Exception as exc:  # noqa: BLE001 — демон не должен падать из-за одного прогона
            logger.error("Ошибка в прогоне #%d: %s", iteration, exc, exc_info=True)

        if max_iterations is not None and iteration >= max_iterations:
            break
        logger.debug("Пауза %d c до следующего прогона", config.poll_interval)
        sleep(config.poll_interval)
    return iteration


def main() -> None:
    config = load_config(require_telegram=True)
    try:
        if config.poll_interval and config.poll_interval > 0:
            run_forever(config)
        else:
            run(config)
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем (KeyboardInterrupt)")
    except Exception as exc:  # noqa: BLE001 — верхний уровень: логируем и падаем с кодом 1
        logger.error("Фатальная ошибка: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
