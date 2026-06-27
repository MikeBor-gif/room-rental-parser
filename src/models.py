"""Модель данных объявления."""

from __future__ import annotations

import html
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Listing:
    """Одно объявление об аренде комнаты.

    Атрибуты:
        id: Стабильный уникальный идентификатор объявления (например, часть URL
            или числовой id с сайта). Используется для дедупликации — должен быть
            одинаковым между прогонами для одного и того же объявления.
        title: Заголовок объявления.
        url: Прямая ссылка на объявление.
        source: Имя парсера/сайта-источника (например, "example_site").
        price: Цена в виде строки (как на сайте) или None, если не определена.
        price_value: Числовое значение цены для фильтрации или None.
        location: Район/адрес или None.
    """

    id: str
    title: str
    url: str
    source: str
    price: str | None = None
    price_value: float | None = None
    location: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_telegram_html(self) -> str:
        """Сформировать текст сообщения для Telegram (parse_mode=HTML)."""
        lines = [f"<b>{html.escape(self.title)}</b>"]
        if self.price:
            lines.append(f"💰 {html.escape(self.price)}")
        if self.location:
            lines.append(f"📍 {html.escape(self.location)}")
        lines.append(f'🔗 <a href="{html.escape(self.url, quote=True)}">{html.escape(self.url)}</a>')
        lines.append(f"<i>источник: {html.escape(self.source)}</i>")
        return "\n".join(lines)
