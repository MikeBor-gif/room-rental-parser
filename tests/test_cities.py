"""Тесты справочника городов и классификации по источникам."""

from src.cities import (
    CITIES,
    CITY_BY_CODE,
    classify_by_name,
    classify_kufar,
    classify_onliner,
    classify_realt,
)


def test_six_regional_cities():
    assert {c.code for c in CITIES} == {
        "minsk", "brest", "vitebsk", "gomel", "grodno", "mogilev",
    }


def test_classify_by_name_normalizes_yo():
    """Kufar отдаёт «Могилев» без ё — оба варианта должны распознаваться."""
    assert classify_by_name("Могилев") == "mogilev"
    assert classify_by_name("Могилёв") == "mogilev"
    assert classify_by_name("  минск ") == "minsk"
    assert classify_by_name("Слуцк") is None
    assert classify_by_name(None) is None


def test_classify_kufar_minsk_by_region():
    # В Минске «Город / Район» — это район города, а не город.
    assert classify_kufar({"Регион": "Минск", "Город / Район": "Советский"}) == "minsk"


def test_classify_kufar_regional_city():
    assert classify_kufar({"Регион": "Витебская область", "Город / Район": "Витебск"}) == "vitebsk"


def test_classify_kufar_small_town_is_none():
    assert classify_kufar({"Регион": "Минская область", "Город / Район": "Слуцк"}) is None
    assert classify_kufar({}) is None


def test_classify_onliner_by_coordinates():
    assert classify_onliner(53.9, 27.56) == "minsk"
    assert classify_onliner(52.09, 23.7) == "brest"
    assert classify_onliner(53.9, 30.33) == "mogilev"
    assert classify_onliner(53.0, 25.0) is None      # чистое поле
    assert classify_onliner(None, None) is None


def test_classify_realt_by_town_name():
    assert classify_realt("Гомель") == "gomel"
    assert classify_realt("Жлобин") is None


def test_city_bounds_do_not_overlap():
    """Рамки городов не пересекаются — объявление попадает максимум в один город."""
    for a in CITIES:
        for b in CITIES:
            if a.code >= b.code:
                continue
            a_lat_min, a_lng_min, a_lat_max, a_lng_max = a.bounds
            b_lat_min, b_lng_min, b_lat_max, b_lng_max = b.bounds
            overlaps = (
                a_lat_min < b_lat_max and b_lat_min < a_lat_max
                and a_lng_min < b_lng_max and b_lng_min < a_lng_max
            )
            assert not overlaps, f"рамки пересекаются: {a.code} и {b.code}"


def test_city_by_code_index():
    assert CITY_BY_CODE["grodno"].name == "Гродно"
