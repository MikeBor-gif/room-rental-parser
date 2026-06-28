"""Парсер «Комнаты в аренду» с onliner.by через публичный JSON-API.

Onliner отдаёт объявления аренды через JSON-API (тот же, что использует карта
на r.onliner.by):

    https://ak.api.onliner.by/search/apartments
    параметры: rent_type[]=room (комнаты), currency=BYN,
               bounds[lb|rt][lat|long] — прямоугольник карты (тут — Минск).

Ответ сортирован по дате поднятия (last_time_up) — сверху недавно поднятые.
Поле created_at у активных объявлений часто старое (владельцы переподнимают
объявление), поэтому «свежесть» считаем по last_time_up, а не по created_at.

Чтобы поменять область/тип — правьте BOUNDS/RENT_TYPE ниже.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

# Максимальный возраст по last_time_up (дате поднятия). Объявления, не
# поднимавшиеся дольше этого срока, считаем неактуальными и не присылаем.
MAX_AGE_DAYS = 3


class OnlinerRoomsParser(BaseParser):
    """Комнаты в аренду на onliner.by (JSON-API, область — Минск)."""

    name = "onliner_rooms"

    API_URL = "https://ak.api.onliner.by/search/apartments"
    RENT_TYPE = "room"
    CURRENCY = "BYN"

    # Прямоугольник карты (Минск), как в ссылке пользователя.
    BOUNDS = {
        "lb": {"lat": "53.757236615705494", "long": "27.301025390625004"},
        "rt": {"lat": "54.03842534637411", "long": "27.822875976562504"},
    }

    HEADERS = {
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": "https://r.onliner.by/ak/",
    }

    def fetch(self) -> list[Listing]:
        params = [
            ("rent_type[]", self.RENT_TYPE),
            ("currency", self.CURRENCY),
            ("bounds[lb][lat]", self.BOUNDS["lb"]["lat"]),
            ("bounds[lb][long]", self.BOUNDS["lb"]["long"]),
            ("bounds[rt][lat]", self.BOUNDS["rt"]["lat"]),
            ("bounds[rt][long]", self.BOUNDS["rt"]["long"]),
        ]
        logger.debug("[%s] Запрос API: %s (params=%s)", self.name, self.API_URL, params)

        raw = self._client.get_text(self.API_URL, params=params, headers=self.HEADERS)
        data = json.loads(raw)
        listings = self.parse(data)
        logger.debug(
            "[%s] total=%s, разобрано объявлений: %d",
            self.name,
            data.get("total"),
            len(listings),
        )
        return listings

    def parse(self, data: dict, now: datetime | None = None) -> list[Listing]:
        """Разобрать JSON-ответ API в список Listing.

        Параметр now (точка отсчёта возраста) нужен для детерминированных тестов;
        в проде не передаётся — берётся текущее UTC-время.
        """
        apartments = data.get("apartments") or []
        results: list[Listing] = []

        for ap in apartments:
            ap_id = ap.get("id")
            if not ap_id:
                logger.warning("[%s] Пропуск объявления без id", self.name)
                continue

            last_up = ap.get("last_time_up", "")
            if _is_too_old(last_up, MAX_AGE_DAYS, now=now):
                logger.info(
                    "[FIX] [%s] Пропуск старого объявления: id=%s last_time_up=%s (порог %d дн.)",
                    self.name,
                    ap_id,
                    last_up,
                    MAX_AGE_DAYS,
                )
                continue

            price_obj = ap.get("price") or {}
            price_str = _format_price(price_obj)
            price_value = _byn_value(price_obj)
            location = ap.get("location") or {}

            results.append(
                Listing(
                    id=f"onliner:{ap_id}",
                    title=_title(ap),
                    url=ap.get("url") or f"https://r.onliner.by/ak/apartments/{ap_id}",
                    source=self.name,
                    price=price_str,
                    price_value=price_value,
                    location=location.get("user_address") or location.get("address"),
                    extra={
                        "created_at": ap.get("created_at", ""),
                        "last_time_up": last_up,
                    },
                )
            )

        return results


def _is_too_old(last_time_up: str, max_age_days: int, *, now: datetime | None = None) -> bool:
    """True, если объявление не поднималось дольше max_age_days (по last_time_up).

    last_time_up приходит в ISO 8601 с таймзоной, напр. '2026-06-28T18:42:36+03:00'.
    При пустом/неразборчивом значении возвращаем False (НЕ отсекаем), чтобы при
    смене формата Onliner не потерять разом всю выдачу — лишь логируем WARN.
    Параметр now (точка отсчёта) нужен для детерминированных тестов.
    """
    if not last_time_up:
        return False
    try:
        bumped = datetime.fromisoformat(last_time_up)
    except ValueError:
        logger.warning(
            "[FIX] [onliner_rooms] Не разобрал last_time_up=%r — не отсекаю", last_time_up
        )
        return False
    if bumped.tzinfo is None:
        bumped = bumped.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - bumped) > timedelta(days=max_age_days)


def _title(ap: dict) -> str:
    """Заголовок: «Комната — <адрес>» (у Onliner нет отдельного headline)."""
    location = ap.get("location") or {}
    address = location.get("user_address") or location.get("address")
    return f"Комната — {address}" if address else "Комната"


def _format_price(price_obj: dict) -> str | None:
    """Строка цены как на сайте: '800 BYN' / '180 USD'."""
    amount = _to_float(price_obj.get("amount"))
    currency = price_obj.get("currency") or ""
    if amount is None:
        return None
    return f"{amount:.0f} {currency}".strip()


def _byn_value(price_obj: dict) -> float | None:
    """Числовая цена в BYN для фильтра max_price.

    Берём price.converted.BYN.amount, чтобы корректно сравнивать с порогом в BYN
    даже когда объявление выставлено в USD.
    """
    converted = (price_obj.get("converted") or {}).get("BYN") or {}
    value = _to_float(converted.get("amount"))
    if value is not None:
        return value if value > 0 else None
    # Фолбэк: если цена и так в BYN — берём напрямую.
    if price_obj.get("currency") == "BYN":
        value = _to_float(price_obj.get("amount"))
        return value if value and value > 0 else None
    return None


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
