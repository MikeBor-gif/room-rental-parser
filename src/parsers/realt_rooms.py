"""Парсер «Комнаты в долгосрочную аренду» с realt.by.

realt.by — Next.js сайт: данные объявлений лежат в JSON внутри страницы
(`<script id="__NEXT_DATA__">`), в `props.pageProps.objects`. HTML отдаётся
с кодом 200 (блокировки нет), нужны лишь браузерные заголовки.

Ссылка на объявление: https://realt.by/rent-rooms-for-long/object/<code>/
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)

# ISO 4217 числовые коды валют, как их отдаёт realt.by.
CURRENCY_BY_CODE = {933: "BYN", 840: "USD", 978: "EUR", 643: "RUB"}

# Максимальный возраст объявления по createdAt. realt.by поднимает в топ списка
# «бумпнутые»/премиум-объявления со старой датой создания, поэтому одной лишь
# сортировки по дате недостаточно — фильтруем по возрасту, чтобы не присылать
# очень старые объявления.
MAX_AGE_DAYS = 3


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

    def parse(self, html_text: str, now: datetime | None = None) -> list[Listing]:
        """Разобрать HTML страницы (через __NEXT_DATA__) в список Listing.

        Параметр now (точка отсчёта возраста) нужен для детерминированных тестов;
        в проде не передаётся — берётся текущее UTC-время.
        """
        objects = self._extract_objects(html_text)
        results: list[Listing] = []

        for obj in objects:
            uuid = obj.get("uuid")
            code = obj.get("code")
            if not uuid:
                logger.warning("[%s] Пропуск объявления без uuid", self.name)
                continue

            created_at = obj.get("createdAt", "")
            if _is_too_old(created_at, MAX_AGE_DAYS, now=now):
                logger.info(
                    "[FIX] [%s] Пропуск старого объявления: code=%s createdAt=%s (порог %d дн.)",
                    self.name,
                    code,
                    created_at,
                    MAX_AGE_DAYS,
                )
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
        logger.warning("[FIX] [realt_rooms] Не разобрал createdAt=%r — не отсекаю", created_at)
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - created) > timedelta(days=max_age_days)


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
