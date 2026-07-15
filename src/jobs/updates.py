"""Обработка апдейтов бота: python -m src.jobs.updates

Работает в режиме long-polling: живёт BOT_LOOP_SECONDS (по умолчанию 240 с)
и слушает Telegram через getUpdates(timeout=25) — сообщение пользователя
обрабатывается через секунды после отправки, а не на следующем прогоне.

Запускается GitHub Actions (bot.yml), который cron-job.org дёргает каждые
~3 минуты: новый прогон отменяет предыдущий (concurrency cancel-in-progress),
так что слушатель почти всегда жив; идемпотентность по last_update_id в БД
делает отмену на середине безопасной.

Лёгкая задача: не импортирует парсеры и bs4 — только httpx + supabase.
ВАЖНО: только эта задача вызывает getUpdates — Telegram допускает один
активный вызов, параллельный получает 409 Conflict.
"""

from __future__ import annotations

import os
import time

from src.bot.router import Router
from src.config import load_config
from src.db import SupabaseDatabase
from src.logging_setup import get_logger
from src.payments.manual import ManualProvider
from src.telegram import TelegramApi

logger = get_logger(__name__)

# Сколько секунд слушать Telegram за один прогон. Вместе с ~40 с на подъём
# машины должно укладываться в timeout-minutes воркфлоу (5 мин): 240 + 40 < 300.
DEFAULT_LOOP_SECONDS = 240
# Таймаут long-polling одного вызова getUpdates (Telegram отвечает мгновенно
# при появлении апдейта, иначе держит соединение до этого срока).
POLL_TIMEOUT_SECONDS = 25


def main() -> None:
    config = load_config(require_telegram=False, require_bot=True)
    # Пустая строка приходит из workflow, если Variable не задана.
    loop_seconds = int(os.getenv("BOT_LOOP_SECONDS") or DEFAULT_LOOP_SECONDS)
    db = SupabaseDatabase(config.supabase_url, config.supabase_service_key)
    provider = ManualProvider(config.tariff_price_byn, config.payment_details)
    try:
        with TelegramApi(config.telegram_bot_token) as api:
            router = Router(db, api, config, provider)
            started = time.monotonic()
            total = iterations = 0
            logger.info("Слушаю Telegram %d с (long-polling %d с)",
                        loop_seconds, POLL_TIMEOUT_SECONDS)
            while time.monotonic() - started < loop_seconds:
                total += router.process_updates(poll_timeout=POLL_TIMEOUT_SECONDS)
                iterations += 1
            logger.info("Прогон завершён: %d апдейтов за %d итераций", total, iterations)
    except Exception as exc:  # noqa: BLE001 — верхний уровень: лог и код 1
        logger.error("Фатальная ошибка updates: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
