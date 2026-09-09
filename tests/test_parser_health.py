"""Тесты алерта админу о замолчавшем парсере (scrape.alert_parser_health)."""

from src.db import FakeDatabase
from src.jobs.scrape import (
    MIN_VOLUME_FOR_ALERT,
    PARSER_COUNT_KEY,
    alert_parser_health,
    count_by_source,
)
from src.models import Listing
from tests.fakes import FakeApi, make_config

PARSER = "realt_rooms"


def _listing(lid: str, source: str) -> Listing:
    return Listing(id=lid, title="T", url="u", source=source, property_type="room")


def _counts(**overrides) -> dict[str, int]:
    counts = count_by_source([])
    counts.update(overrides)
    return counts


def test_counts_include_silent_parsers():
    """Парсер, ничего не вернувший, обязан попасть в счётчики нулём."""
    counts = count_by_source([_listing("a", PARSER), _listing("b", PARSER)])
    assert counts[PARSER] == 2
    assert counts["kufar_rooms"] == 0


def test_alert_on_transition_to_zero():
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    # Первый прогон — улов есть, тревоги нет.
    assert alert_parser_health(db, api, config, _counts(**{PARSER: 30})) == 0
    assert db.get_state(f"{PARSER_COUNT_KEY}{PARSER}") == "30"
    # Второй — ноль: админу уходит алерт.
    assert alert_parser_health(db, api, config, _counts()) == 1
    assert api.sent[0][0] == config.admin_chat_id
    assert PARSER in api.sent[0][1]


def test_no_repeat_alert_while_silent():
    """Пока парсер молчит, алерт шлётся один раз, а не каждые 2 минуты."""
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    alert_parser_health(db, api, config, _counts(**{PARSER: 30}))
    alert_parser_health(db, api, config, _counts())
    assert alert_parser_health(db, api, config, _counts()) == 0
    assert len(api.sent) == 1


def test_recovery_alert():
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    alert_parser_health(db, api, config, _counts(**{PARSER: 30}))
    alert_parser_health(db, api, config, _counts())
    api.sent.clear()
    assert alert_parser_health(db, api, config, _counts(**{PARSER: 12})) == 1
    assert "ожил" in api.sent[0][1]


def test_first_run_never_alerts():
    """Пустого прошлого достаточно для тишины: чистая БД — не повод тревожить."""
    db, api = FakeDatabase(), FakeApi()
    assert alert_parser_health(db, api, make_config(), _counts()) == 0
    assert api.sent == []


def test_no_admin_chat_id_means_no_send():
    db, api = FakeDatabase(), FakeApi()
    config = make_config(admin_chat_id="")
    alert_parser_health(db, api, config, _counts(**{PARSER: 30}))
    assert alert_parser_health(db, api, config, _counts()) == 0
    assert api.sent == []


def test_low_volume_feed_dropping_to_zero_is_not_an_alert():
    """Регрессия из прода: realt_rooms 1 -> 0 не поломка, а пустая лента.

    На realt.by по всей Беларуси одна свежая комната; она выходит за
    MAX_AGE_DAYS и счётчик честно падает в 0. Первая версия алерта слала на
    это тревогу и была бы обречена скакать 1 <-> 0 бесконечно.
    """
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    alert_parser_health(db, api, config, _counts(**{PARSER: 1}))
    assert alert_parser_health(db, api, config, _counts()) == 0
    assert api.sent == []


def test_recovery_of_low_volume_feed_is_silent():
    """И «ожил» на малом объёме тоже молчит — иначе алерт без парного «замолчал»."""
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    alert_parser_health(db, api, config, _counts())
    assert alert_parser_health(db, api, config, _counts(**{PARSER: 1})) == 0
    assert api.sent == []


def test_alert_threshold_boundary():
    """Ровно MIN_VOLUME_FOR_ALERT — уже тревога, на единицу меньше — ещё нет."""
    db, api = FakeDatabase(), FakeApi()
    config = make_config()
    alert_parser_health(db, api, config, _counts(**{PARSER: MIN_VOLUME_FOR_ALERT - 1}))
    assert alert_parser_health(db, api, config, _counts()) == 0

    db2, api2 = FakeDatabase(), FakeApi()
    alert_parser_health(db2, api2, config, _counts(**{PARSER: MIN_VOLUME_FOR_ALERT}))
    assert alert_parser_health(db2, api2, config, _counts()) == 1
