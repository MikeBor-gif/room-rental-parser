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

from src.bot import texts
from src.bot.router import Router
from src.config import load_config
from src.db import Database, SupabaseDatabase
from src.logging_setup import get_logger
from src.payments.manual import ManualProvider
from src.telegram import TelegramApi

logger = get_logger(__name__)

STATE_KEY_COMMANDS_VERSION = "bot_commands_version"


def ensure_menu_button(db: Database, api: TelegramApi) -> None:
    """Зарегистрировать команды бота — Telegram покажет кнопку «Menu» (☰).

    Выполняется один раз на версию списка (флаг в bot_state), а не каждый
    прогон. При неудаче флаг не ставится — повторим на следующем прогоне.
    """
    if db.get_state(STATE_KEY_COMMANDS_VERSION) == texts.BOT_COMMANDS_VERSION:
        return
    ok = api.set_my_commands(texts.BOT_COMMANDS) and api.set_chat_menu_button_commands()
    if ok:
        db.set_state(STATE_KEY_COMMANDS_VERSION, texts.BOT_COMMANDS_VERSION)
        logger.info("[FIX] Кнопка Menu настроена: %d команд (версия %s)",
                    len(texts.BOT_COMMANDS), texts.BOT_COMMANDS_VERSION)
    else:
        logger.warning("[FIX] Не удалось настроить кнопку Menu — повторю на следующем прогоне")

# Сколько секунд слушать Telegram за один прогон. Подобрано под дёрг
# cron-job.org каждые 5 минут: 40 с подъём + 280 с слушания = 320 с > 300 с,
# т.е. следующий прогон отменяет этот, слушатель живёт непрерывно
# (кроме ~40 с подъёма машины). Должно быть < timeout-minutes воркфлоу.
DEFAULT_LOOP_SECONDS = 280
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
            ensure_menu_button(db, api)
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
