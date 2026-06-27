"""Отправка уведомлений в Telegram через Bot API.

Используется метод sendMessage. Зависит только от httpx, без сторонних
библиотек для Telegram, чтобы держать зависимости минимальными.
"""

from __future__ import annotations

import time

import httpx

from src.logging_setup import get_logger
from src.models import Listing

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"
# Telegram ограничивает частоту сообщений; небольшая пауза снижает риск 429.
SEND_PAUSE_SECONDS = 0.5


class TelegramNotifier:
    """Отправщик сообщений в один чат через Telegram Bot API."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        timeout: float = 15.0,
        pause: float = SEND_PAUSE_SECONDS,
        sleep=time.sleep,
    ) -> None:
        if not token or not chat_id:
            raise ValueError("Для TelegramNotifier нужны непустые token и chat_id")
        self._token = token
        self._chat_id = chat_id
        self._pause = pause
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout)
        logger.debug("TelegramNotifier создан для chat_id=%s", chat_id)

    def __enter__(self) -> "TelegramNotifier":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _send_message(self, text: str) -> bool:
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            response = self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.error("Сетевая ошибка при отправке в Telegram: %s", exc)
            return False

        if response.status_code == 200:
            logger.debug("Сообщение отправлено в Telegram")
            return True

        logger.warning(
            "Telegram вернул %s: %s", response.status_code, response.text[:300]
        )
        return False

    def send_listing(self, listing: Listing) -> bool:
        """Отправить одно объявление. Возвращает True при успехе."""
        ok = self._send_message(listing.to_telegram_html())
        self._sleep(self._pause)
        return ok

    def send_listings(self, listings: list[Listing]) -> int:
        """Отправить несколько объявлений. Возвращает число успешных отправок."""
        sent = 0
        for listing in listings:
            if self.send_listing(listing):
                sent += 1
        logger.debug("Отправлено %d/%d объявлений", sent, len(listings))
        return sent
