"""Локальный запуск полного цикла (обёртка над src/jobs/*).

Запуск:
    python -m src.main            # один прогон: апдейты + парсинг + рассылка
    POLL_INTERVAL_SECONDS=120 python -m src.main   # режим демона (VM/Oracle)

В проде на GitHub Actions используются раздельные точки входа:
    python -m src.jobs.updates    # bot.yml, каждую ~1 мин
    python -m src.jobs.scrape     # scrape.yml, каждые 2–3 мин

Здесь оба шага выполняются последовательно в одном процессе — удобно для
локальной отладки и для режима демона на собственной машине.
"""

from __future__ import annotations

import time

from src.bot.router import Router
from src.config import Config, load_config
from src.db import SupabaseDatabase
from src.jobs import scrape
from src.logging_setup import get_logger
from src.payments.manual import ManualProvider
from src.telegram import TelegramApi

logger = get_logger(__name__)


def run(config: Config | None = None) -> dict:
    """Один полный прогон: обработать апдейты, отпарсить, разослать."""
    config = config or load_config(require_telegram=False, require_bot=True)
    db = SupabaseDatabase(config.supabase_url, config.supabase_service_key)
    provider = ManualProvider(config.tariff_price_byn, config.payment_details)
    with TelegramApi(config.telegram_bot_token) as api:
        processed = Router(db, api, config, provider).process_updates()
        stats = scrape.run_cycle(config, db, api)
    stats["updates"] = processed
    return stats


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
    config = load_config(require_telegram=False, require_bot=True)
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
