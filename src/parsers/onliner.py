"""Парсер аренды с onliner.by (комнаты и квартиры, вся Беларусь) через JSON-API.

Onliner отдаёт объявления аренды через JSON-API (тот же, что использует карта
на r.onliner.by):

    https://ak.api.onliner.by/search/apartments
    параметры: rent_type[]=room|1_room|2_rooms|..., currency=BYN,
               bounds[lb|rt][lat|long] — прямоугольник карты.

Рамка — вся Беларусь (см. cities.BELARUS_BOUNDS); город определяется локально
по координатам объявления. Проверено живым запросом (2026-07): по всей стране
комнат ~50, квартир ~800, первая страница (36 шт.) сортирована по last_time_up —
для опроса раз в 2 минуты этого достаточно.

Ответ сортирован по дате поднятия (last_time_up) — сверху недавно поднятые.
Поле created_at у активных объявлений часто старое (владельцы переподнимают
объявление), поэтому «свежесть» считаем по last_time_up, а не по created_at.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.cities import BELARUS_BOUNDS, classify_onliner
from src.logging_setup import get_logger
from src.models import PROPERTY_APARTMENT, PROPERTY_ROOM, Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

# Максимальный возраст по last_time_up (дате поднятия). Объявления, не
# поднимавшиеся дольше этого срока, считаем неактуальными и не присылаем.
MAX_AGE_DAYS = 3

# Человекочитаемые заголовки по rent_type из API.
_RENT_TYPE_LABELS = {
    "room": "Комната",
    "1_room": "1-комнатная квартира",
    "2_rooms": "2-комнатная квартира",
    "3_rooms": "3-комнатная квартира",
    "4_rooms": "4-комнатная квартира",
    "5_rooms": "5-комнатная квартира",
    "6_rooms": "6-комнатная квартира",
}


class OnlinerParser(BaseParser):
    """Базовый парсер Onliner: rent_type задаётся наследником."""

    name = "onliner"
    property_type = PROPERTY_ROOM

    API_URL = "https://ak.api.onliner.by/search/apartments"
    RENT_TYPES: tuple[str, ...] = ("room",)
    CURRENCY = "BYN"

    HEADERS = {
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": "https://r.onliner.by/ak/",
    }

    def fetch(self) -> list[Listing]:
        lat_min, long_min, lat_max, long_max = BELARUS_BOUNDS
        params = [("rent_type[]", rt) for rt in self.RENT_TYPES]
        params += [
            ("currency", self.CURRENCY),
            ("bounds[lb][lat]", str(lat_min)),
            ("bounds[lb][long]", str(long_min)),
            ("bounds[rt][lat]", str(lat_max)),
            ("bounds[rt][long]", str(long_max)),
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
        without_city = 0

        for ap in apartments:
            ap_id = ap.get("id")
            if not ap_id:
                logger.warning("[%s] Пропуск объявления без id", self.name)
                continue

            last_up = ap.get("last_time_up", "")
            if _is_too_old(last_up, MAX_AGE_DAYS, now=now):
                logger.debug(
                    "[%s] Пропуск старого объявления: id=%s last_time_up=%s (порог %d дн.)",
                    self.name, ap_id, last_up, MAX_AGE_DAYS,
                )
                continue

            location = ap.get("location") or {}
            city_code = classify_onliner(location.get("latitude"), location.get("longitude"))
            if city_code is None:
                without_city += 1

            price_obj = ap.get("price") or {}

            results.append(
                Listing(
                    id=f"onliner:{ap_id}",
                    title=_title(ap),
                    url=ap.get("url") or f"https://r.onliner.by/ak/apartments/{ap_id}",
                    source=self.name,
                    property_type=self.property_type,
                    city_code=city_code,
                    photo_url=ap.get("photo") or None,
                    price=_format_price(price_obj),
                    price_value=_byn_value(price_obj),
                    location=location.get("user_address") or location.get("address"),
                    extra={
                        "created_at": ap.get("created_at", ""),
                        "last_time_up": last_up,
                    },
                )
            )

        if without_city:
            logger.debug("[%s] объявлений без распознанного города: %d", self.name, without_city)
        return results


class OnlinerRoomsParser(OnlinerParser):
    """Комнаты в аренду по всей Беларуси."""

    name = "onliner_rooms"
    property_type = PROPERTY_ROOM
    RENT_TYPES = ("room",)


class OnlinerApartmentsParser(OnlinerParser):
    """Квартиры в аренду по всей Беларуси (1–6 комнат)."""

    name = "onliner_flats"
    property_type = PROPERTY_APARTMENT
    RENT_TYPES = ("1_room", "2_rooms", "3_rooms", "4_rooms", "5_rooms", "6_rooms")


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
        logger.warning("[onliner] Не разобрал last_time_up=%r — не отсекаю", last_time_up)
        return False
    if bumped.tzinfo is None:
        bumped = bumped.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - bumped) > timedelta(days=max_age_days)


def _title(ap: dict) -> str:
    """Заголовок: «<тип> — <адрес>» (у Onliner нет отдельного headline)."""
    label = _RENT_TYPE_LABELS.get(ap.get("rent_type", ""), "Жильё")
    location = ap.get("location") or {}
    address = location.get("user_address") or location.get("address")
    return f"{label} — {address}" if address else label


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
