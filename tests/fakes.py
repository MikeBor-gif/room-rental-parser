"""Общие тестовые двойники: Telegram API и конфиг."""

from __future__ import annotations

from pathlib import Path

from src.config import Config


class FakeApi:
    """Двойник TelegramApi: копит отправленное, отдаёт заготовленные апдейты."""

    def __init__(self, updates: list[dict] | None = None):
        self.updates = updates or []
        self.sent: list[tuple] = []          # (chat_id, text)
        self.get_updates_calls: list = []    # переданные offset
        self.blocked_chats: set = set()      # chat_id, «заблокировавшие» бота

    # --- то, что использует роутер/доставка ---

    def get_updates(self, offset=None, timeout=0):
        self.get_updates_calls.append(offset)
        if offset is None:
            return list(self.updates)
        return [u for u in self.updates if u["update_id"] >= offset]

    def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.blocked_chats:
            return {"_blocked": True}
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}

    def send_photo(self, chat_id, photo_url, caption, **kwargs):
        return self.send_message(chat_id, caption)

    def send_listing(self, chat_id, listing):
        if chat_id in self.blocked_chats:
            return {"_blocked": True}
        self.sent.append((chat_id, listing.id))
        return {"ok": True}

    def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return {}

    def answer_callback_query(self, *args, **kwargs):
        pass

    def set_my_commands(self, commands):
        self.commands_set = list(commands)
        return not getattr(self, "fail_setup", False)

    def set_chat_menu_button_commands(self):
        self.menu_button_set = True
        return not getattr(self, "fail_setup", False)

    def set_my_description(self, description):
        self.description_set = description
        return not getattr(self, "fail_setup", False)

    def set_my_short_description(self, short_description):
        self.short_description_set = short_description
        return not getattr(self, "fail_setup", False)

    # --- удобства для проверок ---

    def texts_for(self, chat_id) -> list[str]:
        return [t for c, t in self.sent if c == chat_id]

    @property
    def last_text(self) -> str:
        return self.sent[-1][1] if self.sent else ""


def make_config(tmp_path: Path | None = None, **overrides) -> Config:
    """Конфиг с разумными тестовыми значениями."""
    defaults = dict(
        telegram_bot_token="t",
        telegram_chat_id="",
        log_level="DEBUG",
        max_price=None,
        keywords=[],
        db_path=(tmp_path or Path(".")) / "unused.db",
        admin_chat_id="999",
        tariff_price_byn=15.0,
        free_batch_minutes=30,
        premium_max_filters=5,
        payment_details="Карта 1234 5678",
    )
    defaults.update(overrides)
    return Config(**defaults)


def message_update(update_id: int, chat_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id},
            "from": {"username": "user", "first_name": "Тест"},
            "text": text,
        },
    }


def callback_update(update_id: int, chat_id: int, data: str, message_id: int = 5) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cq{update_id}",
            "data": data,
            "from": {"username": "user", "first_name": "Тест"},
            "message": {"chat": {"id": chat_id}, "message_id": message_id},
        },
    }
