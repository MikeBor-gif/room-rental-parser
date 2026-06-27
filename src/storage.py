"""Хранилище идентификаторов уже отправленных объявлений (SQLite).

Используется для дедупликации: объявление отправляется в Telegram только если
его id ещё не помечен как «виденный». Файл БД (data/seen.db) коммитится обратно
в репозиторий GitHub Actions, чтобы состояние сохранялось между прогонами.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.logging_setup import get_logger

logger = get_logger(__name__)


class SeenStore:
    """Хранилище виденных объявлений поверх SQLite.

    Используется как контекстный менеджер:

        with SeenStore(db_path) as store:
            if not store.is_seen(listing.id):
                ...
                store.mark_seen(listing.id, source=listing.source)
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._ensure_schema()
        logger.debug(
            "SeenStore открыт: %s (записей: %d)", self._db_path, self.count()
        )

    def __enter__(self) -> "SeenStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                id      TEXT PRIMARY KEY,
                source  TEXT,
                seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def is_seen(self, listing_id: str) -> bool:
        """Вернуть True, если объявление с таким id уже сохранено."""
        cur = self._conn.execute(
            "SELECT 1 FROM seen_listings WHERE id = ? LIMIT 1", (listing_id,)
        )
        seen = cur.fetchone() is not None
        logger.debug("is_seen(%s) -> %s", listing_id, seen)
        return seen

    def mark_seen(self, listing_id: str, *, source: str = "") -> None:
        """Пометить объявление как виденное (без ошибки при повторе)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_listings (id, source) VALUES (?, ?)",
            (listing_id, source),
        )
        self._conn.commit()
        logger.debug("mark_seen(%s, source=%s)", listing_id, source)

    def count(self) -> int:
        """Сколько объявлений сохранено всего."""
        cur = self._conn.execute("SELECT COUNT(*) FROM seen_listings")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
        logger.debug("SeenStore закрыт: %s", self._db_path)
