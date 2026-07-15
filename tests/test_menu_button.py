"""Тесты автонастройки кнопки «Menu» (setMyCommands) при старте прогона."""

from src.bot import texts
from src.db import FakeDatabase
from src.jobs.updates import STATE_KEY_COMMANDS_VERSION, ensure_menu_button
from tests.fakes import FakeApi


def test_registers_commands_once():
    db, api = FakeDatabase(), FakeApi()
    ensure_menu_button(db, api)
    assert api.commands_set == texts.BOT_COMMANDS
    assert api.menu_button_set is True
    assert db.get_state(STATE_KEY_COMMANDS_VERSION) == texts.BOT_COMMANDS_VERSION

    # Повторный прогон той же версии — без лишних вызовов API.
    api2 = FakeApi()
    ensure_menu_button(db, api2)
    assert not hasattr(api2, "commands_set")


def test_retries_after_failure():
    db, api = FakeDatabase(), FakeApi()
    api.fail_setup = True
    ensure_menu_button(db, api)
    # Флаг не поставлен — следующий прогон попробует снова.
    assert db.get_state(STATE_KEY_COMMANDS_VERSION) is None
    ok_api = FakeApi()
    ensure_menu_button(db, ok_api)
    assert db.get_state(STATE_KEY_COMMANDS_VERSION) == texts.BOT_COMMANDS_VERSION


def test_new_version_reregisters():
    db, api = FakeDatabase(), FakeApi()
    db.set_state(STATE_KEY_COMMANDS_VERSION, "0")  # старая версия
    ensure_menu_button(db, api)
    assert api.commands_set == texts.BOT_COMMANDS
    assert db.get_state(STATE_KEY_COMMANDS_VERSION) == texts.BOT_COMMANDS_VERSION


def test_profile_registered_once():
    from src.jobs.updates import STATE_KEY_PROFILE_VERSION, ensure_bot_profile

    db, api = FakeDatabase(), FakeApi()
    ensure_bot_profile(db, api)
    assert api.description_set == texts.BOT_DESCRIPTION
    assert api.short_description_set == texts.BOT_SHORT_DESCRIPTION
    assert db.get_state(STATE_KEY_PROFILE_VERSION) == texts.BOT_PROFILE_VERSION
    api2 = FakeApi()
    ensure_bot_profile(db, api2)
    assert not hasattr(api2, "description_set")
