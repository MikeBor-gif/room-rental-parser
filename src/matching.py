"""Матчинг новых объявлений по фильтрам пользователей.

Работает со строками БД (dict), а не с dataclass Listing: на входе — свежие
строки listings (из insert_new_listings) и активные фильтры с вложенными
пользователями (из get_active_filters_with_users).
"""

from __future__ import annotations

from src.logging_setup import get_logger

logger = get_logger(__name__)


def matches(listing: dict, flt: dict) -> bool:
    """Подходит ли объявление под фильтр (тип + город + цена).

    Правила:
    * объявление без распознанного города не матчится никогда;
    * цена None у объявления («договорная» или валюта не BYN) проходит
      любой ценовой фильтр — лучше показать лишнее, чем скрыть подходящее.
    """
    if listing.get("property_type") != flt.get("property_type"):
        return False
    if not listing.get("city_code") or listing["city_code"] != flt.get("city_code"):
        return False
    max_price = flt.get("max_price")
    price_value = listing.get("price_value")
    if max_price is not None and price_value is not None:
        if float(price_value) > float(max_price):
            return False
    return True


def build_deliveries(new_listings: list[dict], filters_with_users: list[dict]) -> list[tuple[int, str]]:
    """Собрать пары (user_id, listing_id) для постановки в очередь доставки.

    Пользователи на паузе или заблокировавшие бота пропускаются.
    Дубликаты (один юзер, одно объявление через два фильтра) схлопываются.
    """
    pairs: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()

    for listing in new_listings:
        for flt in filters_with_users:
            user = flt.get("users") or {}
            if user.get("paused") or user.get("is_blocked"):
                continue
            if not matches(listing, flt):
                continue
            key = (flt["user_id"], listing["id"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)

    logger.debug(
        "Матчинг: новых объявлений=%d, фильтров=%d -> доставок=%d",
        len(new_listings), len(filters_with_users), len(pairs),
    )
    return pairs
