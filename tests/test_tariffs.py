"""Тесты тарифной логики: эффективный тариф, активация, даунгрейд, напоминания."""

from datetime import datetime, timedelta, timezone

from src import tariffs
from src.db import FakeDatabase
from tests.fakes import FakeApi

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _premium_user(db, chat_id=100, days_left=10):
    user = db.upsert_user(chat_id, "u", "U")
    db.update_user(chat_id, {
        "tariff": "premium",
        "paid_until": (NOW + timedelta(days=days_left)).isoformat(),
    })
    return db.get_user(chat_id)


def test_effective_tariff_free_by_default():
    db = FakeDatabase()
    user = db.upsert_user(1, "u", "U")
    assert tariffs.effective_tariff(user, NOW) == "free"


def test_effective_tariff_premium_active():
    db = FakeDatabase()
    user = _premium_user(db)
    assert tariffs.effective_tariff(user, NOW) == "premium"


def test_effective_tariff_expired_premium_is_free():
    """Просроченный премиум считается free ещё ДО даунгрейда в БД."""
    db = FakeDatabase()
    user = _premium_user(db, days_left=-1)
    assert tariffs.effective_tariff(user, NOW) == "free"


def test_filter_limits():
    assert tariffs.filter_limit("free", premium_max_filters=5) == 1
    assert tariffs.filter_limit("premium", premium_max_filters=5) == 5


def test_activate_premium_from_free():
    db = FakeDatabase()
    user = db.upsert_user(1, "u", "U")
    paid_until = tariffs.activate_premium(db, user, now=NOW)
    assert paid_until == NOW + timedelta(days=30)
    assert db.get_user(1)["tariff"] == "premium"


def test_activate_premium_extends_active_subscription():
    """Продление до окончания срока прибавляет 30 дней к ОСТАТКУ, не к сегодня."""
    db = FakeDatabase()
    user = _premium_user(db, days_left=10)
    paid_until = tariffs.activate_premium(db, user, now=NOW)
    assert paid_until == NOW + timedelta(days=40)


def test_downgrade_expired_notifies_user():
    db = FakeDatabase()
    _premium_user(db, chat_id=1, days_left=-1)   # просрочен
    _premium_user(db, chat_id=2, days_left=5)    # активен
    api = FakeApi()

    downgraded = tariffs.downgrade_expired(db, api, now=NOW)

    assert downgraded == 1
    assert db.get_user(1)["tariff"] == "free"
    assert db.get_user(2)["tariff"] == "premium"
    assert len(api.texts_for(1)) == 1


def test_remind_expiring_once():
    db = FakeDatabase()
    _premium_user(db, chat_id=1, days_left=2)    # скоро истечёт
    _premium_user(db, chat_id=2, days_left=20)   # ещё не скоро
    api = FakeApi()

    assert tariffs.remind_expiring(db, api, now=NOW) == 1
    # Повторный вызов не спамит тем же напоминанием.
    assert tariffs.remind_expiring(db, api, now=NOW) == 0
    assert len(api.texts_for(1)) == 1
    assert api.texts_for(2) == []
