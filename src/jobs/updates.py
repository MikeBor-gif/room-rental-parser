"""Обработка апдейтов бота: python -m src.jobs.updates

Забирает накопившиеся сообщения/кнопки через getUpdates и обрабатывает
роутером (см. src/bot/router.py). Лёгкая задача: не импортирует парсеры
и bs4 — только httpx + supabase, чтобы workflow bot.yml стартовал быстро.

Запускается GitHub Actions (bot.yml) каждую ~1 минуту.
ВАЖНО: только эта задача вызывает getUpdates — Telegram допускает один
активный getUpdates на бота (параллельный вызов получит 409 Conflict).
"""

from __future__ import annotations

from src.bot.router import Router
from src.config import load_config
from src.db import SupabaseDatabase
from src.logging_setup import get_logger
from src.payments.manual import ManualProvider
from src.telegram import TelegramApi

logger = get_logger(__name__)


def main() -> None:
    config = load_config(require_telegram=False, require_bot=True)
    db = SupabaseDatabase(config.supabase_url, config.supabase_service_key)
    provider = ManualProvider(config.tariff_price_byn, config.payment_details)
    try:
        with TelegramApi(config.telegram_bot_token) as api:
            router = Router(db, api, config, provider)
            processed = router.process_updates()
            logger.info("Обработано апдейтов: %d", processed)
    except Exception as exc:  # noqa: BLE001 — верхний уровень: лог и код 1
        logger.error("Фатальная ошибка updates: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
