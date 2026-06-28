"""Парсер «Комнаты в аренду, Минск» с Kufar через публичный JSON-API.

HTML-страницы Kufar отдают 403 для не-браузерных запросов, поэтому используем
официальный поисковый API, который отдаёт те же объявления в JSON:

    https://api.kufar.by/search-api/v2/search/rendered
    параметры: cat=1040 (Комнаты), typ=let (аренда), rgn=7 (Минск), lang=ru, size=N

Чтобы добавить другой регион/категорию — поменяйте CAT/RGN/TYP ниже или заведите
отдельный класс-наследник.
"""

from __future__ import annotations

import json

from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)


class KufarRoomsParser(BaseParser):
    """Комнаты в аренду в Минске (Kufar JSON API)."""

    name = "kufar_rooms_minsk"

    API_URL = "https://api.kufar.by/search-api/v2/search/rendered"
    CAT = "1040"   # Комнаты
    TYP = "let"    # аренда
    RGN = "7"      # Минск
    LANG = "ru"
    SIZE = 30      # сколько объявлений запрашивать за раз (по дате — свежие сверху)

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
            "rgn": self.RGN,
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

            price_value = _byn_from_kopecks(ad.get("price_byn"))
            price_str = f"{price_value:.0f} BYN" if price_value is not None else None

            results.append(
                Listing(
                    id=f"kufar:{ad_id}",
                    title=ad.get("subject") or "Без названия",
                    url=ad.get("ad_link") or f"https://re.kufar.by/vi/{ad_id}",
                    source=self.name,
                    price=price_str,
                    price_value=price_value,
                    location=params.get("Город / Район") or params.get("Регион"),
                    extra={"list_time": ad.get("list_time", "")},
                )
            )

        return results


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
