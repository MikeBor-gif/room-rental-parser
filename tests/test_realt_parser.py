"""Тест парсера realt.by на сохранённой HTML-фикстуре (с __NEXT_DATA__)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.parsers.realt_rooms import RealtRoomsParser

FIXTURE = Path(__file__).parent / "fixtures" / "realt_rooms.html"

# Объявления в фикстуре датированы 2026-06-27; фиксируем точку отсчёта возраста,
# чтобы фильтр свежести (MAX_AGE_DAYS) не делал тест зависимым от текущей даты.
FIXTURE_NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)


def _load(now=FIXTURE_NOW):
    html = FIXTURE.read_text(encoding="utf-8")
    return RealtRoomsParser(client=None).parse(html, now=now)


def test_parse_extracts_listings():
    listings = _load()
    assert len(listings) == 3
    assert all(l.id.startswith("realt:") for l in listings)
    assert all(l.source == "realt_rooms" for l in listings)
    # Ссылка строится из code в формате /rent-rooms-for-long/object/<code>/
    assert all(l.url.startswith("https://realt.by/rent-rooms-for-long/object/") for l in listings)


def test_price_and_currency_formatting():
    listings = _load()
    first = listings[0]
    # В фикстуре первое объявление — 650 BYN (код валюты 933).
    assert first.price == "650 BYN"
    assert first.price_value == 650.0


def test_location_includes_town():
    listings = _load()
    assert listings[0].location and "Минск" in listings[0].location


def test_parse_without_next_data_returns_empty():
    assert RealtRoomsParser(client=None).parse("<html><body>no data</body></html>") == []


def _next_data_html(created_at: str) -> str:
    """Собрать минимальную страницу __NEXT_DATA__ с одним объявлением."""
    payload = {
        "props": {
            "pageProps": {
                "objects": [
                    {
                        "uuid": "u-1",
                        "code": 1,
                        "headline": "Комната",
                        "createdAt": created_at,
                    }
                ]
            }
        }
    }
    body = json.dumps(payload)
    return f'<html><body><script id="__NEXT_DATA__">{body}</script></body></html>'


def test_filters_out_old_listing():
    """Регрессия: объявление старше порога (по createdAt) отбрасывается."""
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    old = _next_data_html("2026-01-01T10:00:00+03:00")  # ~полгода назад
    assert RealtRoomsParser(client=None).parse(old, now=now) == []


def test_keeps_fresh_listing():
    """Свежее объявление (в пределах порога) остаётся."""
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    fresh = _next_data_html("2026-06-27T10:00:00+03:00")  # вчера
    listings = RealtRoomsParser(client=None).parse(fresh, now=now)
    assert len(listings) == 1
    assert listings[0].id == "realt:u-1"


def test_unparseable_created_at_is_kept():
    """Битый createdAt не должен молча выкидывать объявление."""
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    broken = _next_data_html("not-a-date")
    assert len(RealtRoomsParser(client=None).parse(broken, now=now)) == 1
