"""Слой доступа к данным: Supabase (Postgres) + in-memory реализация для тестов.

Интерфейс Database описывает все операции с хранилищем. Реализации:

* SupabaseDatabase — продовая, поверх supabase-py (PostgREST).
* FakeDatabase    — in-memory, для тестов (без сети и зависимостей).

Строки таблиц представляются обычными dict (как их отдаёт PostgREST).
"""

from __future__ import annotations

import abc
import itertools
from datetime import datetime, timezone
from typing import Any

from src.logging_setup import get_logger

logger = get_logger(__name__)

Row = dict[str, Any]


def utcnow() -> datetime:
    """Текущее UTC-время (одна точка получения времени для всего кода)."""
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """datetime -> ISO-строка для PostgREST (None остаётся None)."""
    return dt.isoformat() if dt is not None else None


class Database(abc.ABC):
    """Интерфейс хранилища. Все методы синхронные."""

    # --- users ---------------------------------------------------------------

    @abc.abstractmethod
    def upsert_user(self, chat_id: int, username: str | None, first_name: str | None) -> Row:
        """Зарегистрировать пользователя или вернуть существующего."""

    @abc.abstractmethod
    def get_user(self, chat_id: int) -> Row | None:
        """Пользователь по chat_id или None."""

    @abc.abstractmethod
    def get_user_by_id(self, user_id: int) -> Row | None:
        """Пользователь по внутреннему id (PK) или None."""

    @abc.abstractmethod
    def update_user(self, chat_id: int, fields: Row) -> None:
        """Обновить произвольные поля пользователя (dialog_state, tariff...)."""

    @abc.abstractmethod
    def counts(self) -> Row:
        """Счётчики для /stats: total_users, premium_users, active_filters,
        pending_payments, deliveries_24h."""

    @abc.abstractmethod
    def expired_premium_users(self, now: datetime) -> list[Row]:
        """Премиум-пользователи с paid_until < now (для даунгрейда)."""

    @abc.abstractmethod
    def premium_users(self) -> list[Row]:
        """Все пользователи с tariff='premium' (для напоминаний)."""

    @abc.abstractmethod
    def list_users(self, limit: int = 50) -> list[Row]:
        """Последние зарегистрированные пользователи (для админского /users)."""

    # --- feedback ------------------------------------------------------------

    @abc.abstractmethod
    def add_feedback(
        self, user_id: int, chat_id: int, username: str | None, text: str
    ) -> Row:
        """Сохранить отзыв пользователя."""

    # --- filters -------------------------------------------------------------

    @abc.abstractmethod
    def add_filter(
        self, user_id: int, property_type: str, city_code: str, max_price: float | None
    ) -> Row:
        """Создать фильтр пользователя."""

    @abc.abstractmethod
    def get_user_filters(self, user_id: int) -> list[Row]:
        """Все фильтры пользователя (включая выключенные)."""

    @abc.abstractmethod
    def delete_filter(self, filter_id: int) -> None:
        """Удалить фильтр."""

    @abc.abstractmethod
    def set_filter_enabled(self, filter_id: int, enabled: bool) -> None:
        """Включить/выключить фильтр."""

    @abc.abstractmethod
    def get_active_filters_with_users(self) -> list[Row]:
        """Активные фильтры незаблокированных юзеров; в каждой строке — ключ 'users'
        с вложенным словарём пользователя (как отдаёт PostgREST embedding)."""

    # --- listings ------------------------------------------------------------

    @abc.abstractmethod
    def insert_new_listings(self, rows: list[Row]) -> list[Row]:
        """Вставить объявления, игнорируя дубликаты. Вернуть только реально новые."""

    @abc.abstractmethod
    def cleanup_old_rows(self, older_than_days: int) -> None:
        """Удалить старые listings (deliveries удаляются каскадом)."""

    # --- deliveries ----------------------------------------------------------

    @abc.abstractmethod
    def queue_deliveries(self, pairs: list[tuple[int, str]]) -> int:
        """Поставить (user_id, listing_id) в очередь, игнорируя дубликаты.
        Вернуть число реально добавленных."""

    @abc.abstractmethod
    def pending_deliveries(self) -> list[Row]:
        """Неотправленные доставки; в строках — вложенные 'listings' и 'users'."""

    @abc.abstractmethod
    def mark_delivered(self, delivery_id: int, sent_at: datetime) -> None:
        """Пометить доставку отправленной."""

    # --- payments ------------------------------------------------------------

    @abc.abstractmethod
    def create_payment(
        self, user_id: int, amount: float, currency: str, provider: str, order_id: str
    ) -> Row:
        """Создать платёж в статусе pending."""

    @abc.abstractmethod
    def get_payment(self, payment_id: int) -> Row | None:
        """Платёж по id или None."""

    @abc.abstractmethod
    def set_payment_status(self, payment_id: int, status: str, confirmed_at: datetime | None) -> None:
        """Сменить статус платежа."""

    # --- bot_state -----------------------------------------------------------

    @abc.abstractmethod
    def get_state(self, key: str) -> str | None:
        """Значение служебного состояния по ключу."""

    @abc.abstractmethod
    def set_state(self, key: str, value: str) -> None:
        """Записать служебное состояние."""


class SupabaseDatabase(Database):
    """Продовая реализация поверх supabase-py (PostgREST)."""

    def __init__(self, url: str, service_key: str) -> None:
        if not url or not service_key:
            raise ValueError("Для SupabaseDatabase нужны непустые url и service_key")
        # Ленивый импорт: FakeDatabase и тесты не требуют установленный supabase.
        from supabase import create_client

        self._client = create_client(url, service_key)
        logger.debug("SupabaseDatabase создан: %s", url)

    # --- users ---------------------------------------------------------------

    def upsert_user(self, chat_id: int, username: str | None, first_name: str | None) -> Row:
        existing = self.get_user(chat_id)
        if existing is not None:
            logger.debug("upsert_user: chat_id=%s уже зарегистрирован", chat_id)
            return existing
        res = (
            self._client.table("users")
            .insert({"chat_id": chat_id, "username": username, "first_name": first_name})
            .execute()
        )
        logger.info("Новый пользователь: chat_id=%s username=%s", chat_id, username)
        return res.data[0]

    def get_user(self, chat_id: int) -> Row | None:
        res = self._client.table("users").select("*").eq("chat_id", chat_id).limit(1).execute()
        logger.debug("get_user(chat_id=%s) -> %s", chat_id, "найден" if res.data else "нет")
        return res.data[0] if res.data else None

    def get_user_by_id(self, user_id: int) -> Row | None:
        res = self._client.table("users").select("*").eq("id", user_id).limit(1).execute()
        return res.data[0] if res.data else None

    def update_user(self, chat_id: int, fields: Row) -> None:
        self._client.table("users").update(fields).eq("chat_id", chat_id).execute()
        logger.debug("update_user(chat_id=%s): %s", chat_id, sorted(fields))

    def counts(self) -> Row:
        def _count(table: str, query_mod=None) -> int:
            q = self._client.table(table).select("id", count="exact").limit(1)
            if query_mod:
                q = query_mod(q)
            return q.execute().count or 0

        day_ago = datetime.fromtimestamp(utcnow().timestamp() - 86400, tz=timezone.utc)
        result = {
            "total_users": _count("users"),
            "premium_users": _count("users", lambda q: q.eq("tariff", "premium")),
            "active_filters": _count("filters", lambda q: q.eq("enabled", True)),
            "pending_payments": _count("payments", lambda q: q.eq("status", "pending")),
            "deliveries_24h": _count(
                "deliveries", lambda q: q.gte("created_at", iso(day_ago))
            ),
        }
        logger.debug("counts -> %s", result)
        return result

    def expired_premium_users(self, now: datetime) -> list[Row]:
        res = (
            self._client.table("users")
            .select("*")
            .eq("tariff", "premium")
            .lt("paid_until", iso(now))
            .execute()
        )
        logger.debug("expired_premium_users -> %d", len(res.data))
        return res.data

    def premium_users(self) -> list[Row]:
        res = self._client.table("users").select("*").eq("tariff", "premium").execute()
        logger.debug("premium_users -> %d", len(res.data))
        return res.data

    def list_users(self, limit: int = 50) -> list[Row]:
        res = (
            self._client.table("users")
            .select("chat_id, username, first_name, tariff, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        logger.debug("list_users(limit=%d) -> %d", limit, len(res.data))
        return res.data

    # --- feedback ------------------------------------------------------------

    def add_feedback(
        self, user_id: int, chat_id: int, username: str | None, text: str
    ) -> Row:
        res = (
            self._client.table("feedback")
            .insert(
                {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "username": username,
                    "text": text,
                }
            )
            .execute()
        )
        logger.info("Отзыв сохранён: user_id=%s chat_id=%s", user_id, chat_id)
        return res.data[0]

    # --- filters -------------------------------------------------------------

    def add_filter(
        self, user_id: int, property_type: str, city_code: str, max_price: float | None
    ) -> Row:
        res = (
            self._client.table("filters")
            .insert(
                {
                    "user_id": user_id,
                    "property_type": property_type,
                    "city_code": city_code,
                    "max_price": max_price,
                }
            )
            .execute()
        )
        logger.info(
            "Новый фильтр: user_id=%s %s/%s max_price=%s",
            user_id, property_type, city_code, max_price,
        )
        return res.data[0]

    def get_user_filters(self, user_id: int) -> list[Row]:
        res = (
            self._client.table("filters")
            .select("*")
            .eq("user_id", user_id)
            .order("id")
            .execute()
        )
        logger.debug("get_user_filters(user_id=%s) -> %d", user_id, len(res.data))
        return res.data

    def delete_filter(self, filter_id: int) -> None:
        self._client.table("filters").delete().eq("id", filter_id).execute()
        logger.debug("delete_filter(%s)", filter_id)

    def set_filter_enabled(self, filter_id: int, enabled: bool) -> None:
        self._client.table("filters").update({"enabled": enabled}).eq("id", filter_id).execute()
        logger.debug("set_filter_enabled(%s, %s)", filter_id, enabled)

    def get_active_filters_with_users(self) -> list[Row]:
        res = (
            self._client.table("filters")
            .select("*, users!inner(*)")
            .eq("enabled", True)
            .eq("users.is_blocked", False)
            .execute()
        )
        logger.debug("get_active_filters_with_users -> %d", len(res.data))
        return res.data

    # --- listings ------------------------------------------------------------

    def insert_new_listings(self, rows: list[Row]) -> list[Row]:
        if not rows:
            return []
        res = (
            self._client.table("listings")
            .upsert(rows, on_conflict="id", ignore_duplicates=True)
            .execute()
        )
        logger.debug("insert_new_listings: подано=%d, новых=%d", len(rows), len(res.data))
        return res.data

    def cleanup_old_rows(self, older_than_days: int) -> None:
        cutoff = utcnow().timestamp() - older_than_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        self._client.table("listings").delete().lt("first_seen_at", cutoff_iso).execute()
        logger.debug("cleanup_old_rows: удалены listings старше %d дн.", older_than_days)

    # --- deliveries ----------------------------------------------------------

    def queue_deliveries(self, pairs: list[tuple[int, str]]) -> int:
        if not pairs:
            return 0
        rows = [{"user_id": uid, "listing_id": lid} for uid, lid in pairs]
        res = (
            self._client.table("deliveries")
            .upsert(rows, on_conflict="user_id,listing_id", ignore_duplicates=True)
            .execute()
        )
        logger.debug("queue_deliveries: подано=%d, добавлено=%d", len(pairs), len(res.data))
        return len(res.data)

    def pending_deliveries(self) -> list[Row]:
        res = (
            self._client.table("deliveries")
            .select("*, listings(*), users!inner(*)")
            .is_("sent_at", "null")
            .order("id")
            .execute()
        )
        logger.debug("pending_deliveries -> %d", len(res.data))
        return res.data

    def mark_delivered(self, delivery_id: int, sent_at: datetime) -> None:
        self._client.table("deliveries").update({"sent_at": iso(sent_at)}).eq(
            "id", delivery_id
        ).execute()
        logger.debug("mark_delivered(%s)", delivery_id)

    # --- payments ------------------------------------------------------------

    def create_payment(
        self, user_id: int, amount: float, currency: str, provider: str, order_id: str
    ) -> Row:
        res = (
            self._client.table("payments")
            .insert(
                {
                    "user_id": user_id,
                    "amount": amount,
                    "currency": currency,
                    "provider": provider,
                    "order_id": order_id,
                }
            )
            .execute()
        )
        logger.info(
            "Платёж создан: id=%s user_id=%s %s %s (%s)",
            res.data[0]["id"], user_id, amount, currency, provider,
        )
        return res.data[0]

    def get_payment(self, payment_id: int) -> Row | None:
        res = self._client.table("payments").select("*").eq("id", payment_id).limit(1).execute()
        return res.data[0] if res.data else None

    def set_payment_status(self, payment_id: int, status: str, confirmed_at: datetime | None) -> None:
        self._client.table("payments").update(
            {"status": status, "confirmed_at": iso(confirmed_at)}
        ).eq("id", payment_id).execute()
        logger.info("Платёж %s -> %s", payment_id, status)

    # --- bot_state -----------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        res = self._client.table("bot_state").select("value").eq("key", key).limit(1).execute()
        return res.data[0]["value"] if res.data else None

    def set_state(self, key: str, value: str) -> None:
        self._client.table("bot_state").upsert(
            {"key": key, "value": value}, on_conflict="key"
        ).execute()
        logger.debug("set_state(%s)", key)


class FakeDatabase(Database):
    """In-memory реализация для тестов: та же семантика, без сети."""

    def __init__(self) -> None:
        self.users: dict[int, Row] = {}        # по chat_id
        self.filters: dict[int, Row] = {}      # по id
        self.listings: dict[str, Row] = {}     # по id
        self.deliveries: dict[int, Row] = {}   # по id
        self.payments: dict[int, Row] = {}     # по id
        self.feedback: dict[int, Row] = {}     # по id
        self.state: dict[str, str] = {}
        self._ids = itertools.count(1)

    # --- users ---------------------------------------------------------------

    def upsert_user(self, chat_id: int, username: str | None, first_name: str | None) -> Row:
        if chat_id in self.users:
            return self.users[chat_id]
        row = {
            "id": next(self._ids),
            "chat_id": chat_id,
            "username": username,
            "first_name": first_name,
            "tariff": "free",
            "paid_until": None,
            "dialog_state": {},
            "is_admin": False,
            "is_blocked": False,
            "paused": False,
            "last_batch_sent_at": None,
            "created_at": iso(utcnow()),
        }
        self.users[chat_id] = row
        return row

    def get_user(self, chat_id: int) -> Row | None:
        return self.users.get(chat_id)

    def get_user_by_id(self, user_id: int) -> Row | None:
        return next((u for u in self.users.values() if u["id"] == user_id), None)

    def update_user(self, chat_id: int, fields: Row) -> None:
        if chat_id in self.users:
            self.users[chat_id].update(fields)

    def counts(self) -> Row:
        day_ago = utcnow().timestamp() - 86400
        return {
            "total_users": len(self.users),
            "premium_users": sum(1 for u in self.users.values() if u["tariff"] == "premium"),
            "active_filters": sum(1 for f in self.filters.values() if f["enabled"]),
            "pending_payments": sum(
                1 for p in self.payments.values() if p["status"] == "pending"
            ),
            "deliveries_24h": sum(
                1
                for d in self.deliveries.values()
                if datetime.fromisoformat(d["created_at"]).timestamp() >= day_ago
            ),
        }

    def expired_premium_users(self, now: datetime) -> list[Row]:
        result = []
        for user in self.users.values():
            if user["tariff"] != "premium" or not user["paid_until"]:
                continue
            paid_until = user["paid_until"]
            if isinstance(paid_until, str):
                paid_until = datetime.fromisoformat(paid_until)
            if paid_until < now:
                result.append(user)
        return result

    def premium_users(self) -> list[Row]:
        return [u for u in self.users.values() if u["tariff"] == "premium"]

    def list_users(self, limit: int = 50) -> list[Row]:
        return sorted(
            self.users.values(),
            key=lambda u: u.get("created_at") or "",
            reverse=True,
        )[:limit]

    # --- feedback ------------------------------------------------------------

    def add_feedback(
        self, user_id: int, chat_id: int, username: str | None, text: str
    ) -> Row:
        row = {
            "id": next(self._ids),
            "user_id": user_id,
            "chat_id": chat_id,
            "username": username,
            "text": text,
            "created_at": iso(utcnow()),
        }
        self.feedback[row["id"]] = row
        return row

    # --- filters -------------------------------------------------------------

    def add_filter(
        self, user_id: int, property_type: str, city_code: str, max_price: float | None
    ) -> Row:
        row = {
            "id": next(self._ids),
            "user_id": user_id,
            "property_type": property_type,
            "city_code": city_code,
            "max_price": max_price,
            "enabled": True,
            "created_at": iso(utcnow()),
        }
        self.filters[row["id"]] = row
        return row

    def get_user_filters(self, user_id: int) -> list[Row]:
        return sorted(
            (f for f in self.filters.values() if f["user_id"] == user_id),
            key=lambda f: f["id"],
        )

    def delete_filter(self, filter_id: int) -> None:
        self.filters.pop(filter_id, None)

    def set_filter_enabled(self, filter_id: int, enabled: bool) -> None:
        if filter_id in self.filters:
            self.filters[filter_id]["enabled"] = enabled

    def get_active_filters_with_users(self) -> list[Row]:
        users_by_id = {u["id"]: u for u in self.users.values()}
        result = []
        for f in self.filters.values():
            if not f["enabled"]:
                continue
            user = users_by_id.get(f["user_id"])
            if user is None or user["is_blocked"]:
                continue
            result.append({**f, "users": user})
        return result

    # --- listings ------------------------------------------------------------

    def insert_new_listings(self, rows: list[Row]) -> list[Row]:
        new_rows = []
        for row in rows:
            if row["id"] in self.listings:
                continue
            stored = {**row, "first_seen_at": row.get("first_seen_at") or iso(utcnow())}
            self.listings[row["id"]] = stored
            new_rows.append(stored)
        return new_rows

    def cleanup_old_rows(self, older_than_days: int) -> None:
        cutoff = utcnow().timestamp() - older_than_days * 86400
        stale = [
            lid
            for lid, row in self.listings.items()
            if datetime.fromisoformat(row["first_seen_at"]).timestamp() < cutoff
        ]
        for lid in stale:
            del self.listings[lid]
            self.deliveries = {
                did: d for did, d in self.deliveries.items() if d["listing_id"] != lid
            }

    # --- deliveries ----------------------------------------------------------

    def queue_deliveries(self, pairs: list[tuple[int, str]]) -> int:
        existing = {(d["user_id"], d["listing_id"]) for d in self.deliveries.values()}
        added = 0
        for user_id, listing_id in pairs:
            if (user_id, listing_id) in existing:
                continue
            row = {
                "id": next(self._ids),
                "user_id": user_id,
                "listing_id": listing_id,
                "created_at": iso(utcnow()),
                "sent_at": None,
            }
            self.deliveries[row["id"]] = row
            existing.add((user_id, listing_id))
            added += 1
        return added

    def pending_deliveries(self) -> list[Row]:
        users_by_id = {u["id"]: u for u in self.users.values()}
        result = []
        for d in sorted(self.deliveries.values(), key=lambda d: d["id"]):
            if d["sent_at"] is not None:
                continue
            user = users_by_id.get(d["user_id"])
            if user is None:
                continue
            result.append({**d, "listings": self.listings.get(d["listing_id"]), "users": user})
        return result

    def mark_delivered(self, delivery_id: int, sent_at: datetime) -> None:
        if delivery_id in self.deliveries:
            self.deliveries[delivery_id]["sent_at"] = iso(sent_at)

    # --- payments ------------------------------------------------------------

    def create_payment(
        self, user_id: int, amount: float, currency: str, provider: str, order_id: str
    ) -> Row:
        row = {
            "id": next(self._ids),
            "user_id": user_id,
            "tariff": "premium",
            "amount": amount,
            "currency": currency,
            "provider": provider,
            "order_id": order_id,
            "status": "pending",
            "created_at": iso(utcnow()),
            "confirmed_at": None,
        }
        self.payments[row["id"]] = row
        return row

    def get_payment(self, payment_id: int) -> Row | None:
        return self.payments.get(payment_id)

    def set_payment_status(self, payment_id: int, status: str, confirmed_at: datetime | None) -> None:
        if payment_id in self.payments:
            self.payments[payment_id]["status"] = status
            self.payments[payment_id]["confirmed_at"] = iso(confirmed_at)

    # --- bot_state -----------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        return self.state.get(key)

    def set_state(self, key: str, value: str) -> None:
        self.state[key] = value
