"""Тарифная логика: free/premium, лимиты фильтров, активация и истечение подписки.

Тариф хранится в users.tariff, срок — в users.paid_until (timestamptz).
Эффективный тариф считается на лету: premium с истёкшим paid_until — это free
(даунгрейд в БД делает downgrade_expired в scrape-цикле, но проверки лимитов
не должны зависеть от того, успел ли он отработать).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.bot import texts
from src.logging_setup import get_logger

logger = get_logger(__name__)

TARIFF_FREE = "free"
TARIFF_PREMIUM = "premium"

FREE_MAX_FILTERS = 1
PREMIUM_DAYS = 30           # длительность подписки за один платёж
EXPIRY_REMIND_DAYS = 3      # за сколько дней напоминать об окончании


def parse_dt(value: Any) -> datetime | None:
    """paid_until из БД (ISO-строка или datetime) -> aware datetime | None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            logger.warning("Не разобрал дату %r — считаю отсутствующей", value)
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_tariff(user: dict, now: datetime) -> str:
    """Действующий тариф пользователя с учётом срока подписки."""
    if user.get("tariff") == TARIFF_PREMIUM:
        paid_until = parse_dt(user.get("paid_until"))
        if paid_until is not None and paid_until > now:
            return TARIFF_PREMIUM
    return TARIFF_FREE


def filter_limit(tariff: str, premium_max_filters: int) -> int:
    """Максимум фильтров для тарифа."""
    return premium_max_filters if tariff == TARIFF_PREMIUM else FREE_MAX_FILTERS


def activate_premium(db, user: dict, *, days: int = PREMIUM_DAYS,
                     now: datetime | None = None) -> datetime:
    """Включить/продлить премиум: paid_until = max(now, старый срок) + days.

    Возвращает новую дату окончания.
    """
    now = now or datetime.now(timezone.utc)
    current = parse_dt(user.get("paid_until"))
    base = current if current is not None and current > now else now
    paid_until = base + timedelta(days=days)
    db.update_user(user["chat_id"], {
        "tariff": TARIFF_PREMIUM,
        "paid_until": paid_until.isoformat(),
    })
    logger.info(
        "Премиум активирован: chat_id=%s до %s (+%d дн.)",
        user["chat_id"], paid_until.date(), days,
    )
    return paid_until


def downgrade_expired(db, api, now: datetime | None = None) -> int:
    """Перевести просроченный премиум на free и уведомить. Вернуть число даунгрейдов.

    api — TelegramApi (или совместимый объект с send_message); None = без уведомлений.
    """
    now = now or datetime.now(timezone.utc)
    expired = db.expired_premium_users(now)
    for user in expired:
        db.update_user(user["chat_id"], {"tariff": TARIFF_FREE})
        logger.info("Даунгрейд премиума: chat_id=%s (истёк %s)",
                    user["chat_id"], user.get("paid_until"))
        if api is not None:
            api.send_message(user["chat_id"], texts.SUBSCRIPTION_EXPIRED)
    return len(expired)


def remind_expiring(db, api, now: datetime | None = None) -> int:
    """Напомнить о скором окончании подписки (за EXPIRY_REMIND_DAYS дней).

    Повторные напоминания об одном и том же сроке не шлются: факт напоминания
    помечается в dialog_state ключом expiry_reminded_for.
    """
    now = now or datetime.now(timezone.utc)
    reminded = 0
    for user in db.premium_users():
        paid_until = parse_dt(user.get("paid_until"))
        if paid_until is None or paid_until <= now:
            continue
        days_left = (paid_until - now).days
        if days_left >= EXPIRY_REMIND_DAYS:
            continue
        state = dict(user.get("dialog_state") or {})
        marker = paid_until.isoformat()
        if state.get("expiry_reminded_for") == marker:
            continue
        if api is not None:
            api.send_message(user["chat_id"], texts.fmt_subscription_expiring(max(days_left, 1)))
        state["expiry_reminded_for"] = marker
        db.update_user(user["chat_id"], {"dialog_state": state})
        logger.info("Напоминание об окончании подписки: chat_id=%s (%d дн.)",
                    user["chat_id"], days_left)
        reminded += 1
    return reminded
