"""Тесты доставки: батч free, мгновенный премиум, 403 -> is_blocked."""

from datetime import datetime, timedelta, timezone

from src.db import FakeDatabase
from src.delivery import send_pending
from tests.fakes import FakeApi, make_config

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _setup(db, chat_id, tariff="free"):
    user = db.upsert_user(chat_id, "u", "U")
    if tariff == "premium":
        db.update_user(chat_id, {
            "tariff": "premium",
            "paid_until": (NOW + timedelta(days=10)).isoformat(),
        })
    return db.get_user(chat_id)


def _queue(db, user, lid="l1"):
    db.insert_new_listings([{
        "id": lid, "source": "s", "property_type": "room", "city_code": "minsk",
        "title": "T", "url": "u", "photo_url": None,
        "price_str": None, "price_value": None, "location": None,
    }])
    db.queue_deliveries([(user["id"], lid)])


def test_premium_delivered_immediately():
    db, api = FakeDatabase(), FakeApi()
    user = _setup(db, 1, "premium")
    _queue(db, user)
    assert send_pending(db, api, make_config(), now=NOW) == 1


def test_free_first_batch_sent_then_held():
    db, api = FakeDatabase(), FakeApi()
    user = _setup(db, 1)
    _queue(db, user, "l1")
    # Первый батч уходит сразу (last_batch_sent_at пуст).
    assert send_pending(db, api, make_config(), now=NOW) == 1
    # Новая доставка через 5 минут — придержана.
    _queue(db, user, "l2")
    assert send_pending(db, api, make_config(), now=NOW + timedelta(minutes=5)) == 0
    # А через 30+ минут — уходит.
    assert send_pending(db, api, make_config(), now=NOW + timedelta(minutes=31)) == 1


def test_blocked_user_marked_and_skipped():
    db, api = FakeDatabase(), FakeApi()
    user = _setup(db, 1, "premium")
    _queue(db, user, "l1")
    api.blocked_chats.add(1)

    assert send_pending(db, api, make_config(), now=NOW) == 0
    assert db.get_user(1)["is_blocked"] is True
    # Следующий прогон вообще не пытается слать заблокировавшему.
    _queue(db, user, "l2")
    api.blocked_chats.discard(1)
    assert send_pending(db, api, make_config(), now=NOW) == 0


def test_delivery_without_listing_row_closed_silently():
    """Если объявление удалено очисткой — доставка закрывается без отправки."""
    db, api = FakeDatabase(), FakeApi()
    user = _setup(db, 1, "premium")
    _queue(db, user, "l1")
    del db.listings["l1"]

    assert send_pending(db, api, make_config(), now=NOW) == 0
    assert all(d["sent_at"] is not None for d in db.deliveries.values())
