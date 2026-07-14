"""Ручной платёжный провайдер: перевод по реквизитам + подтверждение админом.

Поток:
1. Пользователь жмёт «Оплатить» — бот показывает реквизиты (PAYMENT_DETAILS
   из конфига) и код платежа.
2. Пользователь переводит деньги и жмёт «Я оплатил ✅».
3. Администратору приходит заявка с кнопками «Подтвердить/Отклонить».
4. Подтверждение включает премиум (см. router).

Не требует договора с платёжкой — рабочий вариант с первого дня.
"""

from __future__ import annotations

import time

from src.bot import texts
from src.logging_setup import get_logger
from src.payments.base import Invoice, PaymentProvider

logger = get_logger(__name__)


class ManualProvider(PaymentProvider):
    """Оплата переводом по реквизитам, подтверждение — вручную админом."""

    name = "manual"

    def __init__(self, price_byn: float, payment_details: str) -> None:
        self._price_byn = price_byn
        self._payment_details = payment_details

    def create_invoice(self, chat_id: int, amount: float, currency: str) -> Invoice:
        # Код платежа: узнаваемый и уникальный (chat_id + время).
        order_id = f"M{chat_id}-{int(time.time())}"
        message = texts.fmt_payment_instructions(amount, self._payment_details, order_id)
        logger.info("ManualProvider: счёт %s для chat_id=%s на %s %s",
                    order_id, chat_id, amount, currency)
        return Invoice(order_id=order_id, message_text=message)

    def check_status(self, order_id: str) -> str:
        # Ручной провайдер сам статус не знает — подтверждает администратор.
        return "pending"
