"""Интерфейс платёжного провайдера.

Бот не знает, как именно принимаются деньги, — он работает с PaymentProvider.
Подключение новой платёжки (bepaid, Express-Pay...) = новая реализация этого
интерфейса, роутер и тексты не меняются.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class Invoice:
    """Выставленный счёт: код платежа и текст с инструкцией для пользователя."""

    order_id: str
    message_text: str


class PaymentProvider(abc.ABC):
    """Абстрактный платёжный провайдер."""

    name: str = "base"

    @abc.abstractmethod
    def create_invoice(self, chat_id: int, amount: float, currency: str) -> Invoice:
        """Выставить счёт: вернуть order_id и текст-инструкцию для пользователя."""

    @abc.abstractmethod
    def check_status(self, order_id: str) -> str:
        """Статус платежа у провайдера: 'pending' | 'confirmed' | 'rejected'.

        Для ручного провайдера всегда 'pending' (подтверждает администратор);
        для API-провайдеров — реальный опрос статуса.
        """
