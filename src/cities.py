"""Справочник поддерживаемых городов и классификация объявлений по городу.

Поддерживаются 6 областных центров. Добавление города = одна запись CITIES
(+ координатная рамка для Onliner). Классификация:

* Kufar   — по ad_parameters: «Регион» ('Минск' | '<X> область') и «Город / Район».
* Onliner — по координатам (location.latitude/longitude) через рамки городов.
* Realt   — по имени города (townName из __NEXT_DATA__).

Проверено живыми запросами к API (2026-07): Kufar отдаёт «Могилев» без «ё»,
поэтому все сравнения имён нормализуются (casefold + ё->е).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class City:
    """Один поддерживаемый город."""

    code: str        # стабильный код ('minsk') — хранится в БД
    name: str        # отображаемое имя ('Минск')
    hashtag: str     # хэштег для карточки ('#минск')
    # Координатная рамка (lat_min, long_min, lat_max, long_max) — Onliner.
    bounds: tuple[float, float, float, float]


CITIES: list[City] = [
    City("minsk", "Минск", "#минск", (53.75, 27.30, 54.05, 27.83)),
    City("brest", "Брест", "#брест", (51.95, 23.55, 52.20, 23.90)),
    City("vitebsk", "Витебск", "#витебск", (55.10, 30.05, 55.30, 30.40)),
    City("gomel", "Гомель", "#гомель", (52.35, 30.85, 52.55, 31.10)),
    City("grodno", "Гродно", "#гродно", (53.60, 23.70, 53.75, 24.00)),
    City("mogilev", "Могилёв", "#могилёв", (53.83, 30.20, 54.00, 30.50)),
]

CITY_BY_CODE: dict[str, City] = {c.code: c for c in CITIES}

# Рамка всей Беларуси — для одного общего запроса к Onliner.
BELARUS_BOUNDS: tuple[float, float, float, float] = (51.2, 23.1, 56.2, 32.8)


def _normalize(name: str) -> str:
    """Нормализация имени города: регистр и ё/е ('Могилев' == 'Могилёв')."""
    return name.strip().casefold().replace("ё", "е")


_CITY_BY_NORMALIZED_NAME: dict[str, str] = {_normalize(c.name): c.code for c in CITIES}


def classify_by_name(name: str | None) -> str | None:
    """Код города по его имени ('Витебск' -> 'vitebsk') или None."""
    if not name:
        return None
    code = _CITY_BY_NORMALIZED_NAME.get(_normalize(name))
    logger.debug("classify_by_name(%r) -> %s", name, code)
    return code


def classify_kufar(params: dict[str, str]) -> str | None:
    """Код города из ad_parameters Kufar.

    «Регион» = 'Минск' — сам Минск (в «Город / Район» тогда район города);
    «Регион» = '<X> область' — город лежит в «Город / Район».
    """
    region = params.get("Регион") or ""
    if _normalize(region) == _normalize("Минск"):
        return "minsk"
    code = classify_by_name(params.get("Город / Район"))
    if code is None:
        logger.debug(
            "classify_kufar: город не распознан (Регион=%r, Город/Район=%r)",
            region, params.get("Город / Район"),
        )
    return code


def classify_onliner(latitude: float | None, longitude: float | None) -> str | None:
    """Код города по координатам объявления Onliner (попадание в рамку)."""
    if latitude is None or longitude is None:
        return None
    for city in CITIES:
        lat_min, long_min, lat_max, long_max = city.bounds
        if lat_min <= latitude <= lat_max and long_min <= longitude <= long_max:
            return city.code
    logger.debug("classify_onliner: (%s, %s) вне рамок городов", latitude, longitude)
    return None


def classify_realt(town_name: str | None) -> str | None:
    """Код города по townName объявления Realt."""
    return classify_by_name(town_name)
