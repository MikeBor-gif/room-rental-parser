"""Тест парсера onliner.by на сохранённой JSON-фикстуре (без обращения к сети)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.parsers.onliner import OnlinerRoomsParser

FIXTURE = Path(__file__).parent / "fixtures" / "onliner_rooms.json"

# Объявления в фикстуре подняты 2026-06-28; фиксируем точку отсчёта возраста,
# чтобы фильтр свежести (MAX_AGE_DAYS) не делал тест зависимым от текущей даты.
FIXTURE_NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _load(now=FIXTURE_NOW):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return OnlinerRoomsParser(client=None).parse(data, now=now)


def test_parse_extracts_all_apartments():
    listings = _load()
    assert len(listings) == 3
    assert all(l.id.startswith("onliner:") for l in listings)
    assert all(l.source == "onliner_rooms" for l in listings)
    assert all(l.url.startswith("https://r.onliner.by/ak/apartments/") for l in listings)


def test_byn_price_uses_amount_directly():
    listings = _load()
    byn = next(l for l in listings if l.id == "onliner:939158")
    assert byn.price == "800 BYN"
    assert byn.price_value == 800.0


def test_usd_price_value_comes_from_converted_byn():
    """Цена в USD: показываем USD, но price_value — в BYN из converted (для фильтра)."""
    listings = _load()
    usd = next(l for l in listings if l.id == "onliner:948639")
    assert usd.price == "180 USD"
    assert usd.price_value == 508.10  # converted.BYN.amount


def test_location_and_title_from_address():
    listings = _load()
    first = next(l for l in listings if l.id == "onliner:939158")
    assert first.location and "Минск" in first.location
    assert first.title.startswith("Комната — ")


def test_filters_out_stale_listing():
    """Регрессия: объявление, не поднимавшееся дольше порога, отбрасывается."""
    data = {
        "apartments": [
            {
                "id": 1,
                "price": {"amount": "500.00", "currency": "BYN"},
                "location": {"user_address": "Минск"},
                "last_time_up": "2026-06-01T10:00:00+03:00",  # ~4 недели назад
                "url": "https://r.onliner.by/ak/apartments/1",
            }
        ]
    }
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    assert OnlinerRoomsParser(client=None).parse(data, now=now) == []


def test_unparseable_last_time_up_is_kept():
    """Битый last_time_up не должен молча выкидывать объявление."""
    data = {
        "apartments": [
            {
                "id": 2,
                "price": {"amount": "500.00", "currency": "BYN"},
                "location": {"user_address": "Минск"},
                "last_time_up": "not-a-date",
                "url": "https://r.onliner.by/ak/apartments/2",
            }
        ]
    }
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    assert len(OnlinerRoomsParser(client=None).parse(data, now=now)) == 1


def test_parse_empty_returns_empty():
    assert OnlinerRoomsParser(client=None).parse({"apartments": []}) == []
    assert OnlinerRoomsParser(client=None).parse({}) == []
