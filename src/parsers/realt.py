"""Парсер аренды с realt.by (комнаты и квартиры, вся Беларусь).

realt.by — Next.js сайт: данные объявлений лежат в JSON внутри страницы
(`<script id="__NEXT_DATA__">`), в `props.pageProps.objects`. HTML отдаётся
с кодом 200 (блокировки нет), нужны лишь браузерные заголовки.

Лента общая по стране (сортировка по createdAt), город определяется локально
по townName (см. src/cities.py). Фото — obj.images (cdn.realt.by).

Ссылки на объявления:
    комнаты:  https://realt.by/rent-rooms-for-long/object/<code>/
    квартиры: https://realt.by/rent-flat-for-long/object/<code>/
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from src.cities import classify_realt
from src.logging_setup import get_logger
from src.models import PROPERTY_APARTMENT, PROPERTY_ROOM, Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

# ISO 4217 числовые коды валют, как их отдаёт realt.by.
CURRENCY_BY_CODE = {933: "BYN", 840: "USD", 978: "EUR", 643: "RUB"}
BYN_CODE = 933

# Максимальный возраст объявления по createdAt. realt.by поднимает в топ списка
# «бумпнутые»/премиум-объявления со старой датой создания, поэтому одной лишь
# сортировки по дате недостаточно — фильтруем по возрасту, чтобы не присылать
# очень старые объявления.
MAX_AGE_DAYS = 3


class RealtParser(BaseParser):
    """Базовый парсер realt.by: лента и тип жилья задаются наследником."""

    name = "realt"
    property_type = PROPERTY_ROOM

    LIST_URL = "https://realt.by/rent/room-for-long/?sortType=createdAt&page=1"
    OBJECT_URL = "https://realt.by/rent-rooms-for-long/object/{code}/"
    FALLBACK_URL = "https://realt.by/rent/room-for-long/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    def fetch(self) -> list[Listing]:
        logger.debug("[%s] Загружаю список: %s", self.name, self.LIST_URL)
        html_text = self._client.get_text(self.LIST_URL, headers=self.HEADERS)
        listings = self.parse(html_text)
        logger.debug("[%s] Извлечено объявлений: %d", self.name, len(listings))
        return listings

    def parse(self, html_text: str, now: datetime | None = None) -> list[Listing]:
        """Разобрать HTML страницы (через __NEXT_DATA__) в список Listing.

        Параметр now (точка отсчёта возраста) нужен для детерминированных тестов;
        в проде не передаётся — берётся текущее UTC-время.
        """
        objects = self._extract_objects(html_text)
        results: list[Listing] = []
        without_city = 0

        for obj in objects:
            uuid = obj.get("uuid")
            code = obj.get("code")
            if not uuid:
                logger.warning("[%s] Пропуск объявления без uuid", self.name)
                continue

            created_at = obj.get("createdAt", "")
            if _is_too_old(created_at, MAX_AGE_DAYS, now=now):
                logger.debug(
                    "[%s] Пропуск старого объявления: code=%s createdAt=%s (порог %d дн.)",
                    self.name, code, created_at, MAX_AGE_DAYS,
                )
                continue

            city_code = classify_realt(obj.get("townName"))
            if city_code is None:
                without_city += 1

            url = self.OBJECT_URL.format(code=code) if code else self.FALLBACK_URL

            # Цена приводится к BYN (порог max_price у фильтров — в рублях).
            price_byn = _byn_price_value(obj)

            results.append(
                Listing(
                    id=f"realt:{uuid}",
                    title=(obj.get("headline") or obj.get("title") or "Без названия").strip(),
                    url=url,
                    source=self.name,
                    property_type=self.property_type,
                    city_code=city_code,
                    photo_url=_first_image_url(obj),
                    price=_format_price(obj, price_byn),
                    price_value=price_byn,
                    location=_location(obj),
                    extra={"created_at": obj.get("createdAt", "")},
                )
            )

        if without_city:
            logger.debug("[%s] объявлений без распознанного города: %d", self.name, without_city)
        return results

    def _extract_objects(self, html_text: str) -> list[dict]:
        """Достать props.pageProps.objects из встроенного __NEXT_DATA__."""
        soup = BeautifulSoup(html_text, "html.parser")
        node = soup.find("script", id="__NEXT_DATA__")
        if node is None or not node.string:
            logger.warning("[%s] На странице не найден __NEXT_DATA__", self.name)
            return []
        try:
            data = json.loads(node.string)
            return data["props"]["pageProps"].get("objects") or []
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("[%s] Не удалось разобрать __NEXT_DATA__: %s", self.name, exc)
            return []


class RealtRoomsParser(RealtParser):
    """Комнаты в долгосрочную аренду по всей Беларуси."""

    name = "realt_rooms"
    property_type = PROPERTY_ROOM
    LIST_URL = "https://realt.by/rent/room-for-long/?sortType=createdAt&page=1"
    OBJECT_URL = "https://realt.by/rent-rooms-for-long/object/{code}/"
    FALLBACK_URL = "https://realt.by/rent/room-for-long/"


class RealtApartmentsParser(RealtParser):
    """Квартиры в долгосрочную аренду по всей Беларуси."""

    name = "realt_flats"
    property_type = PROPERTY_APARTMENT
    LIST_URL = "https://realt.by/rent/flat-for-long/?sortType=createdAt&page=1"
    OBJECT_URL = "https://realt.by/rent-flat-for-long/object/{code}/"
    FALLBACK_URL = "https://realt.by/rent/flat-for-long/"


def _is_too_old(created_at: str, max_age_days: int, *, now: datetime | None = None) -> bool:
    """True, если объявление старше max_age_days по полю createdAt.

    createdAt приходит в ISO 8601 с таймзоной, напр. '2026-06-27T22:47:26+03:00'.
    При пустом/неразборчивом значении возвращаем False (НЕ отсекаем), чтобы при
    смене формата realt не потерять разом все объявления — лишь логируем WARN.
    Параметр now (точка отсчёта) нужен для детерминированных тестов.
    """
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        logger.warning("[realt] Не разобрал createdAt=%r — не отсекаю", created_at)
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - created) > timedelta(days=max_age_days)


def _first_image_url(obj: dict) -> str | None:
    """URL первой фотографии (cdn.realt.by) или None."""
    for image in obj.get("images") or []:
        if isinstance(image, str) and image.startswith("http"):
            return image
    return None


def _price_value(price) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _byn_from_rates(obj: dict) -> float | None:
    """Цена в BYN из priceRates — realt.by сам пересчитывает цену по всем валютам.

    priceRates приходит словарём {код валюты ISO 4217: сумма}, ключи — строки:
    {'840': 150, '933': 423, '978': 132, ...}. Подстраховываемся и от числовых.
    """
    rates = obj.get("priceRates")
    if not isinstance(rates, dict):
        return None
    return _price_value(rates.get(str(BYN_CODE), rates.get(BYN_CODE)))


def _byn_price_value(obj: dict) -> float | None:
    """Числовая цена в BYN для фильтра max_price.

    Объявление может быть выставлено в USD/EUR — сравнивать такую сумму с
    порогом в рублях нельзя, поэтому берём пересчёт из priceRates. Если
    пересчёта нет, возвращаем None (объявление пройдёт любой ценовой фильтр,
    как «договорная» цена) и пишем WARN — молча слать дорогое нельзя.
    """
    currency_code = obj.get("priceCurrency")
    if currency_code == BYN_CODE:
        return _price_value(obj.get("price"))

    value = _byn_from_rates(obj)
    if value is None:
        logger.warning(
            "[FIX][realt] Нет BYN в priceRates: code=%s price=%s currency=%s (%s) — "
            "цена не сравнивается с фильтром",
            obj.get("code"), obj.get("price"), currency_code,
            CURRENCY_BY_CODE.get(currency_code, "?"),
        )
        return None
    logger.debug(
        "[FIX][realt] Пересчёт цены: code=%s %s %s -> %.0f BYN",
        obj.get("code"), obj.get("price"),
        CURRENCY_BY_CODE.get(currency_code, currency_code), value,
    )
    return value


def _format_price(obj: dict, price_byn: float | None) -> str | None:
    """Цена для карточки — всегда в BYN, исходная валюта в скобках.

    price_byn считается один раз в parse и передаётся сюда, чтобы не гонять
    пересчёт (и его логи) дважды на одно объявление.
    """
    original = _price_value(obj.get("price"))
    currency = CURRENCY_BY_CODE.get(obj.get("priceCurrency"), "")
    if price_byn is None:
        return f"{original:.0f} {currency}".strip() if original is not None else None
    if original is None or currency in ("", "BYN"):
        return f"{price_byn:.0f} BYN"
    return f"{price_byn:.0f} BYN ({original:.0f} {currency})"


def _location(obj: dict) -> str | None:
    parts = [obj.get("townName"), obj.get("address"), obj.get("metroStationName")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None
