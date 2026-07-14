"""Каркас провайдера bepaid (https://bepaid.by) — подключается в финальной фазе.

Для активации потребуется:
1. Договор с bepaid (нужен ИП/юрлицо), получить shop_id и secret_key.
2. Реализовать create_invoice через POST https://api.bepaid.by/beta/checkouts
   (или /ctp/api/checkouts) — создаёт платёжный токен и redirect_url.
3. Реализовать check_status через GET по token/tracking_id.
4. В create_invoice вернуть Invoice(order_id=<tracking_id>,
   message_text=<текст со ссылкой на оплату>).
5. В scrape-цикле опрашивать pending-платежи bepaid через check_status
   и активировать премиум без участия админа.

Роутер и тексты менять не нужно — они работают через PaymentProvider.
"""

from __future__ import annotations

from src.logging_setup import get_logger
from src.payments.base import Invoice, PaymentProvider

logger = get_logger(__name__)


class BepaidProvider(PaymentProvider):
    """Заглушка bepaid: подключение — после договора с платёжкой."""

    name = "bepaid"

    def __init__(self, shop_id: str, secret_key: str) -> None:
        self._shop_id = shop_id
        self._secret_key = secret_key
        logger.warning("BepaidProvider создан, но интеграция ещё не реализована")

    def create_invoice(self, chat_id: int, amount: float, currency: str) -> Invoice:
        raise NotImplementedError(
            "bepaid ещё не подключён: используйте ManualProvider (см. docstring модуля)"
        )

    def check_status(self, order_id: str) -> str:
        raise NotImplementedError(
            "bepaid ещё не подключён: используйте ManualProvider (см. docstring модуля)"
        )
