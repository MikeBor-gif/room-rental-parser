"""Тесты дедупликации и полного цикла scrape на FakeDatabase."""

from pathlib import Path

from src.config import Config
from src.db import FakeDatabase
from src.jobs import scrape
from src.models import Listing


def _config(tmp_path: Path) -> Config:
    return Config(
        telegram_bot_token="t",
        telegram_chat_id="",
        log_level="DEBUG",
        max_price=None,
        keywords=[],
        db_path=tmp_path / "unused.db",
        free_batch_minutes=30,
    )


def _listing(lid: str, *, city="minsk", ptype="room", price_value=None) -> Listing:
    return Listing(
        id=lid,
        title="Комната",
        url=f"http://x/{lid}",
        source="example_site",
        property_type=ptype,
        city_code=city,
        price=str(price_value) if price_value is not None else None,
        price_value=price_value,
    )


class FakeApi:
    """Минимальный двойник TelegramApi для цикла доставки."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send_listing(self, chat_id, listing):
        self.sent.append((chat_id, listing.id))
        return {"ok": True}

    def send_message(self, chat_id, text, **kwargs):
        return {}


def test_insert_new_listings_deduplicates():
    db = FakeDatabase()
    rows = [_listing("a").to_db_row(), _listing("b").to_db_row()]
    assert len(db.insert_new_listings(rows)) == 2
    # Повторная вставка тех же + одного нового -> новым считается только новый.
    rows2 = [_listing("a").to_db_row(), _listing("c").to_db_row()]
    new = db.insert_new_listings(rows2)
    assert [r["id"] for r in new] == ["c"]


def test_run_cycle_sends_only_new_listings(tmp_path):
    db, api = FakeDatabase(), FakeApi()
    user = db.upsert_user(100, "u", "U")
    db.add_filter(user["id"], "room", "minsk", None)

    sample = [_listing("1", price_value=400.0), _listing("2", price_value=500.0)]
    cfg = _config(tmp_path)

    first = scrape.run_cycle(cfg, db, api, fetch=lambda: sample)
    second = scrape.run_cycle(cfg, db, api, fetch=lambda: sample)

    assert first["new"] == 2 and first["sent"] == 2
    assert second["new"] == 0 and second["sent"] == 0
    assert [lid for _, lid in api.sent] == ["1", "2"]


def test_run_cycle_respects_user_filters(tmp_path):
    db, api = FakeDatabase(), FakeApi()
    user = db.upsert_user(100, "u", "U")
    db.add_filter(user["id"], "room", "minsk", 500)

    sample = [
        _listing("cheap", price_value=400.0),          # проходит
        _listing("pricey", price_value=900.0),         # дороже лимита
        _listing("brest", city="brest"),               # другой город
        _listing("flat", ptype="apartment"),           # другой тип
        _listing("nocity", city=None),                 # без города
    ]
    stats = scrape.run_cycle(_config(tmp_path), db, api, fetch=lambda: sample)

    assert stats["new"] == 5
    assert stats["sent"] == 1
    assert api.sent == [(100, "cheap")]


def test_run_cycle_survives_parser_error(tmp_path):
    """Ошибка fetch отдельного парсера гасится в collect_listings."""

    class BoomParser:
        name = "boom"

        def fetch(self):
            raise RuntimeError("сбой сети")

    class OkParser:
        name = "ok"

        def fetch(self):
            return [_listing("x")]

    listings = scrape.collect_listings([BoomParser(), OkParser()])
    assert [l.id for l in listings] == ["x"]
