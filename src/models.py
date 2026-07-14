"""Модель данных объявления."""

from __future__ import annotations

import html
from dataclasses import dataclass, field

# Типы жилья (значения хранятся в БД, менять нельзя без миграции).
PROPERTY_ROOM = "room"
PROPERTY_APARTMENT = "apartment"

_PROPERTY_LABELS = {PROPERTY_ROOM: "Комната", PROPERTY_APARTMENT: "Квартира"}
_PROPERTY_HASHTAGS = {PROPERTY_ROOM: "#комната", PROPERTY_APARTMENT: "#квартира"}


@dataclass(frozen=True)
class Listing:
    """Одно объявление об аренде (комната или квартира).

    Атрибуты:
        id: Стабильный уникальный идентификатор объявления (например, часть URL
            или числовой id с сайта). Используется для дедупликации — должен быть
            одинаковым между прогонами для одного и того же объявления.
        title: Заголовок объявления.
        url: Прямая ссылка на объявление.
        source: Имя парсера/сайта-источника (например, "kufar").
        property_type: Тип жилья: "room" | "apartment".
        city_code: Код города из src/cities.py ('minsk'...) или None,
            если город не распознан (такие объявления не рассылаются).
        photo_url: URL первой фотографии или None.
        price: Цена в виде строки (как на сайте) или None, если не определена.
        price_value: Числовое значение цены (BYN) для фильтрации или None.
        location: Район/адрес или None.
    """

    id: str
    title: str
    url: str
    source: str
    property_type: str = PROPERTY_ROOM
    city_code: str | None = None
    photo_url: str | None = None
    price: str | None = None
    price_value: float | None = None
    location: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_telegram_html(self) -> str:
        """Сформировать текст карточки для Telegram (parse_mode=HTML).

        Используется и как text в sendMessage, и как caption в sendPhoto.
        """
        type_label = _PROPERTY_LABELS.get(self.property_type, "Жильё")
        lines = [f"<b>{html.escape(f'{type_label}: {self.title}')}</b>"]
        if self.price:
            lines.append(f"💰 {html.escape(self.price)}")
        if self.location:
            lines.append(f"📍 {html.escape(self.location)}")
        lines.append(f'🔗 <a href="{html.escape(self.url, quote=True)}">{html.escape(self.url)}</a>')
        lines.append(self._hashtags())
        lines.append(f"<i>источник: {html.escape(self.source)}</i>")
        return "\n".join(lines)

    def _hashtags(self) -> str:
        """Строка хэштегов: город + тип жилья."""
        # Локальный импорт: не тянуть справочник городов при импорте моделей в тестах.
        from src.cities import CITY_BY_CODE

        tags = []
        city = CITY_BY_CODE.get(self.city_code or "")
        if city:
            tags.append(city.hashtag)
        tags.append(_PROPERTY_HASHTAGS.get(self.property_type, "#жильё"))
        return " ".join(tags)

    def to_db_row(self) -> dict:
        """Строка для вставки в таблицу listings (Supabase)."""
        return {
            "id": self.id,
            "source": self.source,
            "property_type": self.property_type,
            "city_code": self.city_code,
            "title": self.title,
            "url": self.url,
            "photo_url": self.photo_url,
            "price_str": self.price,
            "price_value": self.price_value,
            "location": self.location,
        }
