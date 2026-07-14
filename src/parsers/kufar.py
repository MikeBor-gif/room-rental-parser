"""Парсер аренды с Kufar (комнаты и квартиры, вся Беларусь) через JSON-API.

HTML-страницы Kufar отдают 403 для не-браузерных запросов, поэтому используем
официальный поисковый API, который отдаёт те же объявления в JSON:

    https://api.kufar.by/search-api/v2/search/rendered
    параметры: cat=1040 (Комнаты) | 1010 (Квартиры), typ=let (аренда), lang=ru

Параметр rgn НЕ передаётся — запрашиваем всю страну одним запросом, город
определяем локально из ad_parameters (см. src/cities.py). Проверено живым
запросом (2026-07): «Регион» = 'Минск' | '<X> область', город областных —
в «Город / Район».

Фото: ad.images[].path -> https://rms.kufar.by/v1/gallery/<path> (проверено).
"""

from __future__ import annotations

import json

from src.cities import classify_kufar
from src.logging_setup import get_logger
from src.models import PROPERTY_APARTMENT, PROPERTY_ROOM, Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

IMAGE_BASE = "https://rms.kufar.by/v1/gallery/"


class KufarParser(BaseParser):
    """Базовый парсер Kufar: категория задаётся наследником."""

    name = "kufar"
    property_type = PROPERTY_ROOM

    API_URL = "https://api.kufar.by/search-api/v2/search/rendered"
    CAT = "1040"   # категория Kufar (переопределяется наследником)
    TYP = "let"    # аренда
    LANG = "ru"
    SIZE = 50      # сколько объявлений запрашивать за раз (свежие сверху)

    # API отдаёт JSON; добавляем browser-like заголовки, иначе возможен отказ.
    HEADERS = {
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": "https://re.kufar.by/",
    }

    def fetch(self) -> list[Listing]:
        params = {
            "cat": self.CAT,
            "typ": self.TYP,
            "lang": self.LANG,
            "size": str(self.SIZE),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.API_URL}?{query}"
        logger.debug("[%s] Запрос API: %s", self.name, url)

        raw = self._client.get_text(url, headers=self.HEADERS)
        data = json.loads(raw)
        listings = self.parse(data)
        logger.debug(
            "[%s] total=%s, разобрано объявлений: %d",
            self.name,
            data.get("total"),
            len(listings),
        )
        return listings

    def parse(self, data: dict) -> list[Listing]:
        """Разобрать JSON-ответ API в список Listing.

        Вынесено отдельно от сети, чтобы покрывать тестом на фикстуре.
        """
        ads = data.get("ads") or []
        results: list[Listing] = []
        without_city = 0

        for ad in ads:
            ad_id = ad.get("ad_id") or ad.get("list_id")
            if not ad_id:
                logger.warning("[%s] Пропуск объявления без ad_id", self.name)
                continue

            params = {
                p.get("pl"): p.get("vl")
                for p in (ad.get("ad_parameters") or [])
                if p.get("pl")
            }

            city_code = classify_kufar(params)
            if city_code is None:
                without_city += 1

            price_value = _byn_from_kopecks(ad.get("price_byn"))
            price_str = f"{price_value:.0f} BYN" if price_value is not None else None

            results.append(
                Listing(
                    id=f"kufar:{ad_id}",
                    title=ad.get("subject") or "Без названия",
                    url=ad.get("ad_link") or f"https://re.kufar.by/vi/{ad_id}",
                    source=self.name,
                    property_type=self.property_type,
                    city_code=city_code,
                    photo_url=_first_image_url(ad),
                    price=price_str,
                    price_value=price_value,
                    location=params.get("Город / Район") or params.get("Регион"),
                    extra={"list_time": ad.get("list_time", "")},
                )
            )

        if without_city:
            logger.debug("[%s] объявлений без распознанного города: %d", self.name, without_city)
        return results


class KufarRoomsParser(KufarParser):
    """Комнаты в аренду по всей Беларуси (cat=1040)."""

    name = "kufar_rooms"
    property_type = PROPERTY_ROOM
    CAT = "1040"


class KufarApartmentsParser(KufarParser):
    """Квартиры в долгосрочную аренду по всей Беларуси (cat=1010)."""

    name = "kufar_flats"
    property_type = PROPERTY_APARTMENT
    CAT = "1010"


def _first_image_url(ad: dict) -> str | None:
    """URL первой фотографии объявления или None.

    images[].path -> https://rms.kufar.by/v1/gallery/<path>.
    """
    for image in ad.get("images") or []:
        path = image.get("path")
        if path:
            return f"{IMAGE_BASE}{path}"
    return None


def _byn_from_kopecks(price_byn) -> float | None:
    """Цена в API хранится в копейках: 120000 -> 1200.0 BYN.

    Значение 0 означает «цена не указана» (договорная) — возвращаем None,
    чтобы не показывать вводящее в заблуждение «0 BYN».
    """
    if price_byn in (None, ""):
        return None
    try:
        value = int(price_byn) / 100.0
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
