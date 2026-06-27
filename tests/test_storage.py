"""Тесты хранилища виденных объявлений."""

from src.storage import SeenStore


def test_mark_and_is_seen(tmp_path):
    db = tmp_path / "seen.db"
    with SeenStore(db) as store:
        assert store.is_seen("a") is False
        store.mark_seen("a", source="example")
        assert store.is_seen("a") is True


def test_mark_seen_is_idempotent(tmp_path):
    db = tmp_path / "seen.db"
    with SeenStore(db) as store:
        store.mark_seen("x")
        store.mark_seen("x")
        assert store.count() == 1


def test_state_persists_between_sessions(tmp_path):
    db = tmp_path / "seen.db"
    with SeenStore(db) as store:
        store.mark_seen("persist")
    # Новый объект на том же файле — состояние сохранилось.
    with SeenStore(db) as store2:
        assert store2.is_seen("persist") is True
