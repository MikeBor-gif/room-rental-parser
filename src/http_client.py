"""HTTP-клиент на httpx с таймаутами и ретраями.

Используется парсерами для загрузки страниц. Содержит общий User-Agent,
разумные таймауты и повторные попытки с экспоненциальной паузой.
"""

from __future__ import annotations

import time

import httpx

from src.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # секунды: пауза = base * (2 ** попытка)


class HttpClient:
    """Тонкая обёртка над httpx.Client с ретраями.

    Можно использовать как контекстный менеджер:

        with HttpClient() as client:
            html = client.get_text("https://example.com")
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep=time.sleep,
    ) -> None:
        self._retries = max(1, retries)
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        logger.debug(
            "HttpClient создан: timeout=%s, retries=%s", timeout, self._retries
        )

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        logger.debug("HttpClient закрыт")

    def get_text(self, url: str, **kwargs) -> str:
        """Загрузить URL и вернуть тело ответа как текст.

        Делает до `retries` попыток при сетевых ошибках и ответах 5xx.

        Raises:
            httpx.HTTPError: Если все попытки исчерпаны.
        """
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                logger.debug("GET %s (попытка %d/%d)", url, attempt + 1, self._retries)
                response = self._client.get(url, **kwargs)
                logger.debug("Ответ %s -> %s", url, response.status_code)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Серверная ошибка {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.text
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt + 1 < self._retries:
                    delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Ошибка при GET %s: %s — повтор через %.1f c", url, exc, delay
                    )
                    self._sleep(delay)
                else:
                    logger.error("GET %s окончательно не удался: %s", url, exc)
        assert last_exc is not None
        raise last_exc
