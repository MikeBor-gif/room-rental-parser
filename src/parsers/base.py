"""Базовый интерфейс парсера сайта.

Каждый сайт реализуется отдельным классом-наследником BaseParser в своём файле
внутри src/parsers/. Достаточно реализовать метод fetch().
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from src.http_client import HttpClient
from src.logging_setup import get_logger
from src.models import Listing

logger = get_logger(__name__)


class BaseParser(ABC):
    """Абстрактный парсер одного сайта.

    Атрибуты:
        name: Короткое имя источника (используется в Listing.source и логах).
    """

    name: str = "base"

    def __init__(self, client: HttpClient) -> None:
        self._client = client

    @abstractmethod
    def fetch(self) -> list[Listing]:
        """Загрузить страницу(ы) и вернуть список объявлений.

        Реализация должна:
        - загрузить HTML через self._client.get_text(url);
        - распарсить объявления;
        - вернуть список Listing со стабильным id у каждого.

        Ошибки сети допустимо пробрасывать — оркестратор изолирует падение
        одного парсера и продолжит с остальными.
        """
        raise NotImplementedError

    @staticmethod
    def make_id(source: str, raw: str) -> str:
        """Построить стабильный id из источника и сырого ключа (URL или id сайта).

        Если raw уже выглядит как стабильный идентификатор — можно передать его
        напрямую в Listing.id. Этот помощник удобен, когда стабилен только URL.
        """
        digest = hashlib.sha1(f"{source}:{raw}".encode("utf-8")).hexdigest()[:16]
        return f"{source}:{digest}"
