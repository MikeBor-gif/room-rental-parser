"""Работа с Telegram Bot API: полноценный клиент бота + уведомитель (legacy).

TelegramApi — низкоуровневый клиент: getUpdates, sendMessage, sendPhoto,
inline-клавиатуры, answerCallbackQuery, editMessageText, обработка 429.
Зависит только от httpx, без сторонних библиотек для Telegram.

TelegramNotifier — прежний односторонний отправитель в один чат (используется
старым оркестратором src/main.py и тестами); оставлен для совместимости.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.logging_setup import get_logger
from src.models import Listing

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"
# Telegram ограничивает частоту сообщений; небольшая пауза снижает риск 429.
SEND_PAUSE_SECONDS = 0.5
# Максимум повторов после 429 (retry_after) на один вызов.
MAX_RATE_LIMIT_RETRIES = 2


class TelegramApi:
    """Клиент Telegram Bot API для произвольных чатов.

    Используется как контекстный менеджер:

        with TelegramApi(token) as api:
            api.send_message(chat_id, "Привет")
    """

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 35.0,
        sleep=time.sleep,
    ) -> None:
        if not token:
            raise ValueError("Для TelegramApi нужен непустой token")
        self._token = token
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "TelegramApi":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # --- низкоуровневый вызов -------------------------------------------------

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Вызвать метод Bot API. Вернуть result или None при ошибке.

        429 (rate limit) обрабатывается: пауза retry_after и повтор
        (до MAX_RATE_LIMIT_RETRIES раз).
        """
        url = f"{API_BASE}/bot{self._token}/{method}"
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                logger.error("Сетевая ошибка Telegram %s: %s", method, exc)
                return None

            if response.status_code == 200:
                data = response.json()
                logger.debug("Telegram %s -> ok", method)
                return data.get("result")

            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                logger.warning(
                    "Telegram 429 на %s: пауза %d с (попытка %d/%d)",
                    method, retry_after, attempt + 1, MAX_RATE_LIMIT_RETRIES,
                )
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    self._sleep(retry_after)
                    continue
                return None

            logger.warning(
                "Telegram %s вернул %s: %s (chat_id=%s)",
                method, response.status_code, response.text[:300], payload.get("chat_id"),
            )
            # 403 = юзер заблокировал бота — прокидываем понятный маркер вызывающему.
            if response.status_code == 403:
                return {"_blocked": True}
            return None
        return None

    # --- обновления -----------------------------------------------------------

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict[str, Any]]:
        """Забрать накопившиеся апдейты (сообщения, callback_query).

        offset = last_update_id + 1: подтверждает все предыдущие апдейты.
        """
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result = self.call("getUpdates", payload)
        updates = result if isinstance(result, list) else []
        logger.debug("get_updates(offset=%s) -> %d апдейтов", offset, len(updates))
        return updates

    # --- отправка -------------------------------------------------------------

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_markup: dict | None = None,
        disable_preview: bool = True,
    ) -> dict[str, Any] | None:
        """Отправить текстовое сообщение (HTML)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def send_photo(
        self,
        chat_id: int | str,
        photo_url: str,
        caption: str,
        *,
        reply_markup: dict | None = None,
    ) -> dict[str, Any] | None:
        """Отправить фото с подписью (HTML). Фолбэк на текст — у вызывающего."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call("sendPhoto", payload)

    def send_listing(self, chat_id: int | str, listing: Listing) -> dict[str, Any] | None:
        """Отправить карточку объявления: фото с подписью или текст без фото.

        Если Telegram не смог загрузить фото по URL — повторяем текстом.
        Возвращает result Telegram, {'_blocked': True} если юзер заблокировал
        бота, или None при прочей ошибке.
        """
        text = listing.to_telegram_html()
        if listing.photo_url:
            result = self.send_photo(chat_id, listing.photo_url, text)
            if result is not None:
                self._sleep(SEND_PAUSE_SECONDS)
                return result
            logger.warning(
                "sendPhoto не удался (%s), фолбэк на текст: %s", listing.id, listing.photo_url
            )
        result = self.send_message(chat_id, text, disable_preview=False)
        self._sleep(SEND_PAUSE_SECONDS)
        return result

    # --- настройка бота ---------------------------------------------------------

    def set_my_commands(self, commands: list[tuple[str, str]]) -> bool:
        """Зарегистрировать список команд бота (setMyCommands).

        После этого Telegram сам показывает кнопку «Menu» (☰) рядом с полем
        ввода во всех личных чатах с ботом.
        """
        payload = {
            "commands": [{"command": cmd, "description": desc} for cmd, desc in commands]
        }
        result = self.call("setMyCommands", payload)
        logger.debug("setMyCommands (%d команд) -> %s", len(commands), result is not None)
        return result is not None

    def set_chat_menu_button_commands(self) -> bool:
        """Явно включить кнопку меню типа «commands» (setChatMenuButton)."""
        result = self.call("setChatMenuButton", {"menu_button": {"type": "commands"}})
        logger.debug("setChatMenuButton(commands) -> %s", result is not None)
        return result is not None

    def set_my_description(self, description: str) -> bool:
        """Описание в пустом чате до нажатия «Старт» (до 512 символов)."""
        result = self.call("setMyDescription", {"description": description})
        logger.debug("setMyDescription -> %s", result is not None)
        return result is not None

    def set_my_short_description(self, short_description: str) -> bool:
        """Короткое описание в профиле и при пересылке (до 120 символов)."""
        result = self.call("setMyShortDescription", {"short_description": short_description})
        logger.debug("setMyShortDescription -> %s", result is not None)
        return result is not None

    # --- интерактив -----------------------------------------------------------

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        """Подтвердить нажатие inline-кнопки (убирает «часики» у юзера)."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self.call("answerCallbackQuery", payload)

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ) -> dict[str, Any] | None:
        """Изменить текст ранее отправленного сообщения (для меню)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call("editMessageText", payload)


def inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """Собрать inline-клавиатуру из [(текст, callback_data), ...] по строкам."""
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": data} for text, data in row]
            for row in rows
        ]
    }


def _retry_after_seconds(response: httpx.Response) -> int:
    """Достать parameters.retry_after из ответа 429 (по умолчанию 3 с)."""
    try:
        return int(response.json()["parameters"]["retry_after"])
    except Exception:  # noqa: BLE001 — формат может отличаться, дефолт безопасен
        return 3


class TelegramNotifier:
    """Отправщик сообщений в один чат (legacy, для старого оркестратора)."""

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
