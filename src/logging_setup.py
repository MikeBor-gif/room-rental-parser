"""Настройка логирования по переменной окружения LOG_LEVEL."""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def setup_logging() -> None:
    """Сконфигурировать корневой логгер один раз.

    Уровень берётся из LOG_LEVEL (DEBUG | INFO | WARNING | ERROR).
    По умолчанию INFO. Повторные вызовы безопасны (idempotent).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _CONFIGURED = True
    logging.getLogger(__name__).debug("Логирование настроено, уровень=%s", level_name)


def get_logger(name: str) -> logging.Logger:
    """Вернуть логгер с гарантированно настроенной конфигурацией."""
    setup_logging()
    return logging.getLogger(name)
