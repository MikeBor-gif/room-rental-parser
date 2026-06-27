"""Парсер-ШАБЛОН (заглушка).

Это рабочий пример того, как реализовать парсер реального сайта. Сейчас он
парсит демонстрационную HTML-разметку (см. селекторы ниже). Когда вы пришлёте
ссылки на настоящие сайты, скопируйте этот файл, поменяйте URL и CSS-селекторы
под конкретный сайт — и зарегистрируйте парсер в src/main.py (список PARSERS).

Структура HTML, которую ожидает этот шаблон (замените под реальный сайт):

    <div class="listing" data-id="123">
        <a class="listing-title" href="/ad/123">Уютная комната в центре</a>
        <span class="listing-price">500 EUR</span>
        <span class="listing-location">Центр</span>
    </div>
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.logging_setup import get_logger
from src.models import Listing
from src.parsers.base import BaseParser

logger = get_logger(__name__)


class ExampleSiteParser(BaseParser):
    """Шаблон парсера. Замените BASE_URL/LIST_URL и селекторы под реальный сайт."""

    name = "example_site"

    # TODO(ссылки от пользователя): заменить на реальные URL сайта.
    BASE_URL = "https://example.com"
    LIST_URL = "https://example.com/rooms"

    def fetch(self) -> list[Listing]:
        logger.debug("[%s] Загружаю список: %s", self.name, self.LIST_URL)
        html_text = self._client.get_text(self.LIST_URL)
        listings = self.parse(html_text)
        logger.debug("[%s] Извлечено объявлений: %d", self.name, len(listings))
        return listings

    def parse(self, html_text: str) -> list[Listing]:
        """Разобрать HTML списка в объявления.

        Вынесено в отдельный метод, чтобы покрывать тестом на HTML-фикстуре
        без обращения к сети.
        """
        soup = BeautifulSoup(html_text, "html.parser")
        results: list[Listing] = []

        for node in soup.select("div.listing"):
            title_el = node.select_one("a.listing-title")
            if title_el is None:
                logger.debug("[%s] Пропуск блока без заголовка", self.name)
                continue

            href = title_el.get("href", "")
            url = urljoin(self.BASE_URL, href)

            # Стабильный id: предпочитаем data-id сайта, иначе хэш от URL.
            raw_id = node.get("data-id") or href
            listing_id = (
                f"{self.name}:{raw_id}" if node.get("data-id") else self.make_id(self.name, url)
            )

            price_el = node.select_one("span.listing-price")
            location_el = node.select_one("span.listing-location")
            price = price_el.get_text(strip=True) if price_el else None

            results.append(
                Listing(
                    id=listing_id,
                    title=title_el.get_text(strip=True),
                    url=url,
                    source=self.name,
                    price=price,
                    price_value=_extract_price_value(price),
                    location=location_el.get_text(strip=True) if location_el else None,
                )
            )

        return results


def _extract_price_value(price: str | None) -> float | None:
    """Вытащить число из строки цены ('500 EUR' -> 500.0)."""
    if not price:
        return None
    digits = "".join(ch for ch in price if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None
