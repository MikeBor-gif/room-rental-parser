"""Тесты роутера бота: диалоги, лимиты тарифов, платежи, идемпотентность."""

from datetime import datetime, timedelta, timezone

from src.bot.router import Router
from src.db import FakeDatabase
from src.payments.manual import ManualProvider
from tests.fakes import FakeApi, callback_update, make_config, message_update

USER = 100
ADMIN = 999


def _router(updates=None):
    db = FakeDatabase()
    api = FakeApi(updates)
    cfg = make_config()
    provider = ManualProvider(cfg.tariff_price_byn, cfg.payment_details)
    return Router(db, api, cfg, provider), db, api


def _create_filter(router, db, api, chat_id=USER, start_id=1):
    """Прогнать конструктор фильтра: /add -> квартира -> Гомель -> до 500."""
    router._handle_update(message_update(start_id, chat_id, "/add"))
    router._handle_update(callback_update(start_id + 1, chat_id, "prop:apartment"))
    router._handle_update(callback_update(start_id + 2, chat_id, "city:gomel"))
    router._handle_update(callback_update(start_id + 3, chat_id, "price:500"))


# --- регистрация и конструктор фильтра ---------------------------------------


def test_start_registers_user_and_greets():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    assert db.get_user(USER) is not None
    assert "Привет" in api.last_text


def test_filter_flow_creates_filter():
    router, db, api = _router()
    _create_filter(router, db, api)
    user = db.get_user(USER)
    filters = db.get_user_filters(user["id"])
    assert len(filters) == 1
    f = filters[0]
    assert (f["property_type"], f["city_code"], f["max_price"]) == ("apartment", "gomel", 500.0)
    assert user["dialog_state"] == {}  # диалог завершён


def test_typed_price_accepted():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    router._handle_update(callback_update(3, USER, "city:minsk"))
    router._handle_update(message_update(4, USER, "650"))
    f = db.get_user_filters(db.get_user(USER)["id"])
    assert f and f[0]["max_price"] == 650.0


def test_typed_price_garbage_reprompts():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    router._handle_update(callback_update(3, USER, "city:minsk"))
    router._handle_update(message_update(4, USER, "дёшево"))
    assert db.get_user_filters(db.get_user(USER)["id"]) == []
    assert "число" in api.last_text.lower()


def test_price_any_saves_null_price():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    router._handle_update(callback_update(3, USER, "city:brest"))
    router._handle_update(callback_update(4, USER, "price:any"))
    f = db.get_user_filters(db.get_user(USER)["id"])
    assert f and f[0]["max_price"] is None


# --- лимиты тарифов -------------------------------------------------------------


def test_free_user_limited_to_one_filter():
    router, db, api = _router()
    _create_filter(router, db, api)
    router._handle_update(message_update(10, USER, "/add"))
    assert "бесплатном тарифе" in api.last_text
    assert len(db.get_user_filters(db.get_user(USER)["id"])) == 1


def test_premium_user_can_add_more_filters():
    router, db, api = _router()
    _create_filter(router, db, api)
    db.update_user(USER, {
        "tariff": "premium",
        "paid_until": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
    })
    _create_filter(router, db, api, start_id=10)
    assert len(db.get_user_filters(db.get_user(USER)["id"])) == 2


# --- управление фильтрами ---------------------------------------------------------


def test_delete_and_toggle_filter():
    router, db, api = _router()
    _create_filter(router, db, api)
    f = db.get_user_filters(db.get_user(USER)["id"])[0]

    router._handle_update(callback_update(10, USER, f"ftog:{f['id']}"))
    assert db.filters[f["id"]]["enabled"] is False
    router._handle_update(callback_update(11, USER, f"fdel:{f['id']}"))
    assert db.get_user_filters(db.get_user(USER)["id"]) == []


def test_cannot_manage_foreign_filter():
    router, db, api = _router()
    _create_filter(router, db, api)
    foreign_id = db.get_user_filters(db.get_user(USER)["id"])[0]["id"]

    router._handle_update(callback_update(10, 200, f"fdel:{foreign_id}"))
    # Фильтр цел: чужой пользователь не может его удалить.
    assert len(db.get_user_filters(db.get_user(USER)["id"])) == 1


# --- оплата ------------------------------------------------------------------------


def _pay_flow(router, db, api):
    router._handle_update(message_update(1, USER, "/premium"))
    router._handle_update(callback_update(2, USER, "pay:new"))
    payment_id = next(iter(db.payments))
    router._handle_update(callback_update(3, USER, f"paid:{payment_id}"))
    return payment_id


def test_payment_flow_notifies_admin():
    router, db, api = _router()
    _pay_flow(router, db, api)
    admin_msgs = api.texts_for("999")
    assert admin_msgs and "заявка на оплату" in admin_msgs[-1].lower()


def test_admin_confirm_activates_premium():
    router, db, api = _router()
    payment_id = _pay_flow(router, db, api)
    router._handle_update(callback_update(4, ADMIN, f"apay:{payment_id}"))

    assert db.payments[payment_id]["status"] == "confirmed"
    user = db.get_user(USER)
    assert user["tariff"] == "premium" and user["paid_until"]
    assert any("Премиум активирован" in t for t in api.texts_for(USER))


def test_admin_reject_keeps_user_free():
    router, db, api = _router()
    payment_id = _pay_flow(router, db, api)
    router._handle_update(callback_update(4, ADMIN, f"rpay:{payment_id}"))

    assert db.payments[payment_id]["status"] == "rejected"
    assert db.get_user(USER)["tariff"] == "free"


def test_non_admin_cannot_confirm_payment():
    router, db, api = _router()
    payment_id = _pay_flow(router, db, api)
    router._handle_update(callback_update(4, USER, f"apay:{payment_id}"))
    assert db.payments[payment_id]["status"] == "pending"


def test_double_confirm_is_noop():
    router, db, api = _router()
    payment_id = _pay_flow(router, db, api)
    router._handle_update(callback_update(4, ADMIN, f"apay:{payment_id}"))
    paid_until_first = db.get_user(USER)["paid_until"]
    router._handle_update(callback_update(5, ADMIN, f"apay:{payment_id}"))
    # Повторное подтверждение не продлевает подписку второй раз.
    assert db.get_user(USER)["paid_until"] == paid_until_first


def test_grant_command():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    router._handle_update(message_update(2, ADMIN, f"/grant {USER} 7"))
    assert db.get_user(USER)["tariff"] == "premium"


# --- идемпотентность и служебное ------------------------------------------------------


def test_process_updates_is_idempotent():
    updates = [message_update(7, USER, "/start"), message_update(8, USER, "/help")]
    router, db, api = _router(updates)

    assert router.process_updates() == 2
    assert db.get_state("last_update_id") == "8"
    # Второй прогон запрашивает offset=9 и ничего не обрабатывает повторно.
    sent_before = len(api.sent)
    assert router.process_updates() == 0
    assert api.get_updates_calls[-1] == 9
    assert len(api.sent) == sent_before


def test_poison_update_does_not_stall_queue():
    """Апдейт, роняющий обработчик, помечается обработанным и не зацикливает бота."""
    updates = [
        {"update_id": 1, "message": {"chat": {"id": USER}}},  # без text — просто скип
        {"update_id": 2},                                      # неизвестный тип
        message_update(3, USER, "/help"),
    ]
    router, db, api = _router(updates)
    assert router.process_updates() == 3
    assert db.get_state("last_update_id") == "3"


def test_pause_resume():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/pause"))
    assert db.get_user(USER)["paused"] is True
    router._handle_update(message_update(2, USER, "/resume"))
    assert db.get_user(USER)["paused"] is False


def test_unknown_command_gets_help_hint():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/abracadabra"))
    assert "/help" in api.last_text


def test_stats_admin_only():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/stats"))
    assert "администратору" in api.last_text
    router._handle_update(message_update(2, ADMIN, "/stats"))
    assert "Статистика" in api.last_text


# --- навигация по меню и «Назад» ------------------------------------------------


def test_menu_button_shows_main_menu():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    router._handle_update(callback_update(2, USER, "menu"))
    assert "Главное меню" in api.last_text
    assert "Бесплатный" in api.last_text


def test_menu_shows_premium_status():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    db.update_user(USER, {
        "tariff": "premium",
        "paid_until": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
    })
    router._handle_update(callback_update(2, USER, "menu"))
    assert "Премиум" in api.last_text


def test_back_from_city_returns_to_property_step():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    assert "городе" in api.last_text.lower()
    router._handle_update(callback_update(3, USER, "back:property"))
    assert "Что ищем" in api.last_text
    # После возврата можно выбрать другой тип и пройти до конца.
    router._handle_update(callback_update(4, USER, "prop:apartment"))
    router._handle_update(callback_update(5, USER, "city:minsk"))
    router._handle_update(callback_update(6, USER, "price:any"))
    f = db.get_user_filters(db.get_user(USER)["id"])
    assert f and f[0]["property_type"] == "apartment"


def test_back_from_price_returns_to_city_step():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    router._handle_update(callback_update(3, USER, "city:brest"))
    assert "цена" in api.last_text.lower()
    router._handle_update(callback_update(4, USER, "back:city"))
    assert "городе" in api.last_text.lower()
    # Тип жилья сохранён — выбираем другой город и завершаем.
    router._handle_update(callback_update(5, USER, "city:gomel"))
    router._handle_update(callback_update(6, USER, "price:500"))
    f = db.get_user_filters(db.get_user(USER)["id"])
    assert f and f[0]["city_code"] == "gomel" and f[0]["property_type"] == "room"


def test_menu_resets_dialog_state():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/add"))
    router._handle_update(callback_update(2, USER, "prop:room"))
    router._handle_update(callback_update(3, USER, "menu"))
    assert db.get_user(USER)["dialog_state"] == {}


def test_toggle_pause_from_menu():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    router._handle_update(callback_update(2, USER, "toggle:pause"))
    assert db.get_user(USER)["paused"] is True
    assert "на паузе" in api.last_text
    router._handle_update(callback_update(3, USER, "toggle:pause"))
    assert db.get_user(USER)["paused"] is False


def test_delete_refreshes_filters_screen():
    router, db, api = _router()
    _create_filter(router, db, api)
    f = db.get_user_filters(db.get_user(USER)["id"])[0]
    router._handle_update(callback_update(10, USER, f"fdel:{f['id']}"))
    # Экран обновился на месте и показывает пустой список, а не отдельное сообщение.
    assert "нет фильтров" in api.last_text.lower()


def test_show_screens_from_menu():
    router, db, api = _router()
    router._handle_update(message_update(1, USER, "/start"))
    router._handle_update(callback_update(2, USER, "show:help"))
    assert "Как пользоваться" in api.last_text
    router._handle_update(callback_update(3, USER, "show:premium"))
    assert "Премиум" in api.last_text
    router._handle_update(callback_update(4, USER, "show:filters"))
    assert "фильтр" in api.last_text.lower()
