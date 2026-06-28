"""Конфигурация приложения из переменных окружения.

Для локального запуска значения берутся из окружения процесса. Файл .env
(если есть) подгружается простым парсером без внешних зависимостей.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.logging_setup import get_logger

logger = get_logger(__name__)

# Корень проекта (каталог, содержащий этот пакет src/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "seen.db"


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env: KEY=VALUE построчно, без зависимостей.

    Существующие переменные окружения не перезаписываются.
    """
    if not path.exists():
        logger.debug(".env не найден (%s) — используется только окружение процесса", path)
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    logger.debug("Загружены значения из .env: %s", path)


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", ".").strip())
    except ValueError:
        logger.warning("Не удалось разобрать число из %r — игнорирую", value)
        return None


def _parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [kw.strip().lower() for kw in value.split(",") if kw.strip()]


def _parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError:
        logger.warning("Не удалось разобрать целое из %r — использую %d", value, default)
        return default


@dataclass(frozen=True)
class Config:
    """Разобранная конфигурация приложения."""

    telegram_bot_token: str
    telegram_chat_id: str
    log_level: str
    max_price: float | None
    keywords: list[str]
    db_path: Path
    # Интервал опроса в секундах для режима демона (VM). 0 = один прогон и выход
    # (режим для GitHub Actions). >0 = бесконечный цикл с паузой между прогонами.
    poll_interval: int = 0

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_config(*, require_telegram: bool = True) -> Config:
    """Собрать конфигурацию из окружения (с подгрузкой .env).

    Args:
        require_telegram: Если True — отсутствие токена/chat_id вызывает ошибку.
            Для тестов/частичных запусков можно передать False.

    Raises:
        RuntimeError: Если require_telegram=True и не заданы токен или chat_id.
    """
    _load_dotenv(PROJECT_ROOT / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    max_price = _parse_float(os.getenv("MAX_PRICE"))
    keywords = _parse_keywords(os.getenv("KEYWORDS"))
    poll_interval = _parse_int(os.getenv("POLL_INTERVAL_SECONDS"), default=0)

    if require_telegram and (not token or not chat_id):
        raise RuntimeError(
            "Не заданы TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHAT_ID. "
            "Укажите их в окружении или в .env (см. .env.example)."
        )

    # Логируем факт загрузки конфигурации БЕЗ раскрытия секретов.
    logger.debug(
        "Конфигурация загружена: telegram=%s, max_price=%s, keywords=%d шт., log_level=%s",
        "задан" if (token and chat_id) else "НЕ задан",
        max_price,
        len(keywords),
        log_level,
    )

    return Config(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        log_level=log_level,
        max_price=max_price,
        keywords=keywords,
        db_path=DEFAULT_DB_PATH,
        poll_interval=poll_interval,
    )
