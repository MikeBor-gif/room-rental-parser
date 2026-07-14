"""Отправка очереди доставок пользователям с учётом тарифа.

Премиум — все pending сразу (каждый прогон scrape, ~2–4 мин задержки).
Free — батчем: только если с последней рассылки прошло FREE_BATCH_MINUTES.

403 от Telegram (юзер заблокировал бота) — помечаем is_blocked, его доставки
больше не шлём. Ошибка отправки одного сообщения не валит остальные.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src import tariffs
from src.config import Config
from src.db import Database
from src.logging_setup import get_logger
from src.models import Listing
from src.telegram import TelegramApi

logger = get_logger(__name__)


def listing_from_row(row: dict) -> Listing:
    """Строка listings из БД -> Listing (для форматирования карточки)."""
    return Listing(
        id=row["id"],
        title=row.get("title") or "Без названия",
        url=row.get("url") or "",
        source=row.get("source") or "",
        property_type=row.get("property_type") or "room",
        city_code=row.get("city_code"),
        photo_url=row.get("photo_url"),
        price=row.get("price_str"),
        price_value=float(row["price_value"]) if row.get("price_value") is not None else None,
        location=row.get("location"),
    )


def send_pending(db: Database, api: TelegramApi, config: Config,
                 now: datetime | None = None) -> int:
    """Отправить назревшие доставки. Вернуть число отправленных сообщений."""
    now = now or datetime.now(timezone.utc)
    pending = db.pending_deliveries()
    if not pending:
        logger.info("Очередь доставки пуста")
        return 0

    # Группируем по пользователю, чтобы решать «пора ли» один раз на юзера.
    by_user: dict[int, list[dict]] = {}
    for d in pending:
        by_user.setdefault(d["user_id"], []).append(d)

    sent = errors = skipped_users = 0
    for user_id, deliveries in by_user.items():
        user = deliveries[0].get("users") or {}
        if user.get("is_blocked") or user.get("paused"):
            skipped_users += 1
            continue

        tariff = tariffs.effective_tariff(user, now)
        if tariff == tariffs.TARIFF_FREE and not _free_batch_due(user, config, now):
            skipped_users += 1
            logger.debug("free-батч ещё не назрел: chat_id=%s", user.get("chat_id"))
            continue

        user_sent = 0
        blocked = False
        for d in deliveries:
            listing_row = d.get("listings")
            if not listing_row:
                # Объявление удалено (cleanup) — закрываем доставку без отправки.
                db.mark_delivered(d["id"], now)
                continue
            result = api.send_listing(user["chat_id"], listing_from_row(listing_row))
            if isinstance(result, dict) and result.get("_blocked"):
                logger.warning("chat_id=%s заблокировал бота — помечаю is_blocked",
                               user.get("chat_id"))
                db.update_user(user["chat_id"], {"is_blocked": True})
                blocked = True
                break
            if result is None:
                errors += 1
                continue
            db.mark_delivered(d["id"], now)
            user_sent += 1

        sent += user_sent
        if user_sent and not blocked and tariff == tariffs.TARIFF_FREE:
            db.update_user(user["chat_id"], {"last_batch_sent_at": now.isoformat()})

    logger.info(
        "Доставка: pending=%d, юзеров=%d, отправлено=%d, ошибок=%d, отложено юзеров=%d",
        len(pending), len(by_user), sent, errors, skipped_users,
    )
    return sent


def _free_batch_due(user: dict, config: Config, now: datetime) -> bool:
    """Пора ли слать батч free-пользователю (прошло ли FREE_BATCH_MINUTES)."""
    last = tariffs.parse_dt(user.get("last_batch_sent_at"))
    if last is None:
        return True
    return (now - last).total_seconds() >= config.free_batch_minutes * 60
