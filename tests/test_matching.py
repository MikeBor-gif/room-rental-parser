"""Тесты матчинга объявлений по фильтрам пользователей."""

from src.db import FakeDatabase
from src.matching import build_deliveries, matches


def _listing(lid="x", ptype="room", city="minsk", price=None):
    return {"id": lid, "property_type": ptype, "city_code": city, "price_value": price}


def _filter(ptype="room", city="minsk", max_price=None, user=None):
    return {
        "user_id": (user or {}).get("id", 1),
        "property_type": ptype,
        "city_code": city,
        "max_price": max_price,
        "users": user or {},
    }


def test_matches_type_city_price():
    assert matches(_listing(), _filter())
    assert not matches(_listing(ptype="apartment"), _filter())
    assert not matches(_listing(city="brest"), _filter())
    assert not matches(_listing(price=700), _filter(max_price=500))
    assert matches(_listing(price=400), _filter(max_price=500))


def test_listing_without_city_never_matches():
    assert not matches(_listing(city=None), _filter())


def test_negotiable_price_passes_price_filter():
    """Цена None (договорная/не BYN) проходит любой ценовой фильтр."""
    assert matches(_listing(price=None), _filter(max_price=300))


def test_build_deliveries_skips_paused_and_blocked():
    db = FakeDatabase()
    active = db.upsert_user(1, "a", "A")
    paused = db.upsert_user(2, "p", "P")
    blocked = db.upsert_user(3, "b", "B")
    db.update_user(2, {"paused": True})
    db.update_user(3, {"is_blocked": True})
    for u in (active, paused, blocked):
        db.add_filter(u["id"], "room", "minsk", None)

    pairs = build_deliveries([_listing()], db.get_active_filters_with_users())

    assert pairs == [(active["id"], "x")]


def test_build_deliveries_deduplicates_across_filters():
    """Два фильтра одного юзера, оба матчатся -> одна доставка."""
    db = FakeDatabase()
    user = db.upsert_user(1, "a", "A")
    db.add_filter(user["id"], "room", "minsk", None)
    db.add_filter(user["id"], "room", "minsk", 1000)

    pairs = build_deliveries(
        [_listing(price=500)], db.get_active_filters_with_users()
    )
    assert pairs == [(user["id"], "x")]
