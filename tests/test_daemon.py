"""Тесты режима демона (run_forever)."""

from pathlib import Path

from src import main as M
from src.config import Config


def _config(tmp_path: Path, interval: int) -> Config:
    return Config(
        telegram_bot_token="t",
        telegram_chat_id="c",
        log_level="DEBUG",
        max_price=None,
        keywords=[],
        db_path=tmp_path / "seen.db",
        poll_interval=interval,
    )


def test_run_forever_runs_n_iterations(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(M, "run", lambda cfg: calls.__setitem__("n", calls["n"] + 1))
    sleeps: list[int] = []

    iterations = M.run_forever(
        _config(tmp_path, interval=120),
        max_iterations=3,
        sleep=lambda s: sleeps.append(s),
    )

    assert iterations == 3
    assert calls["n"] == 3
    # Пауза между прогонами, но не после последнего.
    assert sleeps == [120, 120]


def test_run_forever_survives_run_errors(tmp_path, monkeypatch):
    def boom(cfg):
        raise RuntimeError("сбой прогона")

    monkeypatch.setattr(M, "run", boom)

    # Не должно выбросить наружу — ошибки логируются, цикл продолжается.
    iterations = M.run_forever(
        _config(tmp_path, interval=1),
        max_iterations=2,
        sleep=lambda s: None,
    )
    assert iterations == 2
