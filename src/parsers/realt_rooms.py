"""Парсер «Комнаты в долгосрочную аренду» с realt.by.

realt.by — Next.js сайт: данные объявлений лежат в JSON внутри страницы
(`<script id="__NEXT_DATA__">`), в `props.pageProps.objects`. HTML отдаётся
с кодом 200 (блокировки нет), нужны лишь браузерные заголовки.

Ссылка на объявление: https://realt.by/rent-rooms-for-long/object/<code>/
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

# ISO 4217 числовые коды валют, как их отдаёт realt.by.
CURRENCY_BY_CODE = {933: "BYN", 840: "USD", 978: "EUR", 643: "RUB"}


class RealtRoomsParser(BaseParser):
    """Комнаты в долгосрочную аренду с realt.by (сортировка по дате создания)."""

    name = "realt_rooms"

    LIST_URL = "https://realt.by/rent/room-for-long/?sortType=createdAt&page=1"
    OBJECT_URL = "https://realt.by/rent-rooms-for-long/object/{code}/"

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

    def parse(self, html_text: str) -> list[Listing]:
        """Разобрать HTML страницы (через __NEXT_DATA__) в список Listing."""
        objects = self._extract_objects(html_text)
        results: list[Listing] = []

        for obj in objects:
            uuid = obj.get("uuid")
            code = obj.get("code")
            if not uuid:
                logger.warning("[%s] Пропуск объявления без uuid", self.name)
                continue

            price_value = _price_value(obj.get("price"))
            price_str = _format_price(obj.get("price"), obj.get("priceCurrency"))
            url = (
                self.OBJECT_URL.format(code=code)
                if code
                else "https://realt.by/rent/room-for-long/"
            )

            results.append(
                Listing(
                    id=f"realt:{uuid}",
                    title=(obj.get("headline") or obj.get("title") or "Без названия").strip(),
                    url=url,
                    source=self.name,
                    price=price_str,
                    price_value=price_value,
                    location=_location(obj),
                    extra={"created_at": obj.get("createdAt", "")},
                )
            )

        return results

    @staticmethod
    def _extract_objects(html_text: str) -> list[dict]:
        """Достать props.pageProps.objects из встроенного __NEXT_DATA__."""
        soup = BeautifulSoup(html_text, "html.parser")
        node = soup.find("script", id="__NEXT_DATA__")
        if node is None or not node.string:
            logger.warning("[realt_rooms] На странице не найден __NEXT_DATA__")
            return []
        try:
            data = json.loads(node.string)
            return data["props"]["pageProps"].get("objects") or []
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("[realt_rooms] Не удалось разобрать __NEXT_DATA__: %s", exc)
            return []


def _price_value(price) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _format_price(price, currency_code) -> str | None:
    value = _price_value(price)
    if value is None:
        return None
    currency = CURRENCY_BY_CODE.get(currency_code, "")
    return f"{value:.0f} {currency}".strip()


def _location(obj: dict) -> str | None:
    parts = [obj.get("townName"), obj.get("address"), obj.get("metroStationName")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None
