"""Тест парсера realt.by на сохранённой HTML-фикстуре (с __NEXT_DATA__)."""

from pathlib import Path

from src.parsers.realt_rooms import RealtRoomsParser

FIXTURE = Path(__file__).parent / "fixtures" / "realt_rooms.html"


def _load():
    html = FIXTURE.read_text(encoding="utf-8")
    return RealtRoomsParser(client=None).parse(html)


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
