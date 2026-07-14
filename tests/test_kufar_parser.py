"""Тест парсера Kufar на сохранённой JSON-фикстуре (без обращения к сети)."""

import json
from pathlib import Path

from src.parsers.kufar import KufarRoomsParser

FIXTURE = Path(__file__).parent / "fixtures" / "kufar_rooms.json"


def _load():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return KufarRoomsParser(client=None).parse(data)


def test_parse_extracts_all_ads():
    listings = _load()
    assert len(listings) == 3
    assert all(l.id.startswith("kufar:") for l in listings)
    assert all(l.url.startswith("https://") for l in listings)
    assert all(l.source == "kufar_rooms" for l in listings)
    assert all(l.property_type == "room" for l in listings)


def test_priced_ad_converts_kopecks_to_byn():
    listings = _load()
    priced = next(l for l in listings if l.id == "kufar:1074927439")
    assert priced.price_value == 705.70  # 70570 копеек -> BYN
    assert priced.price == "706 BYN"
    assert priced.title


def test_zero_price_becomes_none():
    listings = _load()
    # Объявления с price_byn == 0 (договорная) не должны показывать "0 BYN".
    zero = [l for l in listings if l.id == "kufar:1074930631"]
    assert zero, "ожидалось объявление с нулевой ценой в фикстуре"
    assert zero[0].price_value is None
    assert zero[0].price is None


def test_parse_empty_returns_empty():
    assert KufarRoomsParser(client=None).parse({"ads": []}) == []
    assert KufarRoomsParser(client=None).parse({}) == []
