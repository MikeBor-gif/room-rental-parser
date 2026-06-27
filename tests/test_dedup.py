"""Тесты дедупликации и фильтрации в оркестраторе."""

from pathlib import Path

import pytest

from src import main as M
from src.config import Config
from src.models import Listing
from src.storage import SeenStore


def _config(tmp_path: Path, *, max_price=None, keywords=None) -> Config:
    return Config(
        telegram_bot_token="t",
        telegram_chat_id="c",
        log_level="DEBUG",
        max_price=max_price,
        keywords=keywords or [],
        db_path=tmp_path / "seen.db",
    )


def _listing(lid: str, *, title="Комната", price_value=None, location=None) -> Listing:
    return Listing(
        id=lid,
        title=title,
        url=f"http://x/{lid}",
        source="example_site",
        price=str(price_value) if price_value is not None else None,
        price_value=price_value,
        location=location,
    )


def test_select_new_excludes_seen(tmp_path):
    with SeenStore(tmp_path / "seen.db") as store:
        store.mark_seen("a")
        new = M.select_new([_listing("a"), _listing("b")], store)
    assert [l.id for l in new] == ["b"]


def test_apply_filters_by_price(tmp_path):
    cfg = _config(tmp_path, max_price=500.0)
    listings = [_listing("a", price_value=400.0), _listing("b", price_value=900.0)]
    result = M.apply_filters(listings, cfg)
    assert [l.id for l in result] == ["a"]


def test_apply_filters_by_keyword(tmp_path):
    cfg = _config(tmp_path, keywords=["центр"])
    listings = [
        _listing("a", title="Комната", location="Центр города"),
        _listing("b", title="Студия", location="Север"),
    ]
    result = M.apply_filters(listings, cfg)
    assert [l.id for l in result] == ["a"]


def test_run_sends_only_new_listings(tmp_path, monkeypatch):
    sample = [_listing("1", price_value=400.0, location="Центр"),
              _listing("2", price_value=400.0, location="Центр")]

    monkeypatch.setattr(M, "collect_listings", lambda parsers: sample)

    sent_ids: list[str] = []

    class FakeNotifier:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def send_listing(self, listing):
            sent_ids.append(listing.id)
            return True

    monkeypatch.setattr(M, "TelegramNotifier", FakeNotifier)

    cfg = _config(tmp_path)
    first = M.run(cfg)
    second = M.run(cfg)

    assert first == 2
    assert second == 0
    assert sent_ids == ["1", "2"]
