"""Тесты парсеров квартир и извлечения города/фото (на инлайн-фикстурах)."""

import json
from datetime import datetime, timezone

from src.parsers.kufar import KufarApartmentsParser
from src.parsers.onliner import OnlinerApartmentsParser
from src.parsers.realt import RealtApartmentsParser

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


# --- Kufar ---------------------------------------------------------------------


def _kufar_ad(ad_id, region, city_or_district, price_byn=90000, images=True):
    return {
        "ad_id": ad_id,
        "subject": f"Квартира {ad_id}",
        "ad_link": f"https://re.kufar.by/vi/{ad_id}",
        "price_byn": price_byn,
        "images": [{"path": f"adim1/{ad_id}.jpg", "media_storage": "rms"}] if images else [],
        "ad_parameters": [
            {"pl": "Регион", "vl": region},
            {"pl": "Город / Район", "vl": city_or_district},
        ],
    }


def test_kufar_apartments_city_photo_type():
    data = {"ads": [
        _kufar_ad(1, "Минск", "Фрунзенский"),
        _kufar_ad(2, "Гродненская область", "Гродно"),
        _kufar_ad(3, "Минская область", "Слуцк"),          # не поддерживаемый город
        _kufar_ad(4, "Могилевская область", "Могилев", images=False),
    ]}
    listings = KufarApartmentsParser(client=None).parse(data)

    assert [l.city_code for l in listings] == ["minsk", "grodno", None, "mogilev"]
    assert all(l.property_type == "apartment" for l in listings)
    assert listings[0].photo_url == "https://rms.kufar.by/v1/gallery/adim1/1.jpg"
    assert listings[3].photo_url is None
    assert listings[0].price_value == 900.0  # копейки -> BYN


# --- Onliner -------------------------------------------------------------------


def _onliner_ap(ap_id, lat, lng, rent_type="2_rooms"):
    return {
        "id": ap_id,
        "rent_type": rent_type,
        "price": {"amount": "800", "currency": "BYN",
                  "converted": {"BYN": {"amount": "800"}}},
        "location": {"address": f"Адрес {ap_id}", "user_address": f"Адрес {ap_id}",
                     "latitude": lat, "longitude": lng},
        "photo": f"https://content.onliner.by/{ap_id}.jpg",
        "url": f"https://r.onliner.by/ak/apartments/{ap_id}",
        "created_at": "2026-07-14T10:00:00+03:00",
        "last_time_up": "2026-07-14T10:00:00+03:00",
    }


def test_onliner_apartments_city_from_coordinates():
    data = {"apartments": [
        _onliner_ap(1, 53.9, 27.56),      # Минск
        _onliner_ap(2, 55.19, 30.20),     # Витебск
        _onliner_ap(3, 53.0, 25.0),       # вне городов
    ]}
    listings = OnlinerApartmentsParser(client=None).parse(data, now=NOW)

    assert [l.city_code for l in listings] == ["minsk", "vitebsk", None]
    assert all(l.property_type == "apartment" for l in listings)
    assert listings[0].photo_url == "https://content.onliner.by/1.jpg"
    assert "2-комнатная квартира" in listings[0].title


def test_onliner_old_listing_filtered_by_last_time_up():
    stale = _onliner_ap(9, 53.9, 27.56)
    stale["last_time_up"] = "2026-07-01T10:00:00+03:00"  # старше 3 дней
    listings = OnlinerApartmentsParser(client=None).parse({"apartments": [stale]}, now=NOW)
    assert listings == []


# --- Realt ---------------------------------------------------------------------


def _realt_html(objects) -> str:
    payload = {"props": {"pageProps": {"objects": objects}}}
    return (
        "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    )


def _realt_obj(uuid, town, price=900, currency=933):
    return {
        "uuid": f"u-{uuid}",
        "code": uuid,
        "title": f"Квартира {uuid}",
        "headline": f"Квартира {uuid}",
        "price": price,
        "priceCurrency": currency,
        "townName": town,
        "address": "ул. Тестовая 1",
        "images": [f"https://cdn.realt.by/img/{uuid}-1", f"https://cdn.realt.by/img/{uuid}-2"],
        "createdAt": "2026-07-14T09:00:00+03:00",
    }


def test_realt_apartments_city_photo_url():
    html = _realt_html([
        _realt_obj(1, "Могилёв"),
        _realt_obj(2, "Борисов"),
    ])
    listings = RealtApartmentsParser(client=None).parse(html, now=NOW)

    assert [l.city_code for l in listings] == ["mogilev", None]
    assert all(l.property_type == "apartment" for l in listings)
    assert listings[0].photo_url == "https://cdn.realt.by/img/1-1"
    assert listings[0].url == "https://realt.by/rent-flat-for-long/object/1/"


def test_realt_usd_price_not_used_for_byn_filter():
    """Цена в USD не сравнивается с порогом в BYN: price_value = None."""
    html = _realt_html([_realt_obj(1, "Минск", price=300, currency=840)])
    listings = RealtApartmentsParser(client=None).parse(html, now=NOW)
    assert listings[0].price == "300 USD"
    assert listings[0].price_value is None
