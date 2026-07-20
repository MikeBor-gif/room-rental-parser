"""Роутер апдейтов Telegram: команды, кнопки, диалог настройки фильтра, оплата.

Обрабатывает message и callback_query из getUpdates. Состояние диалога
(конструктор фильтра) хранится в users.dialog_state (jsonb) — процесс
короткоживущий (GitHub Actions), в памяти ничего не держим.

Идемпотентность: last_update_id хранится в bot_state и обновляется после
обработки КАЖДОГО апдейта — при падении/отмене прогона посередине уже
обработанные апдейты не выполняются повторно.

Навигация: каждый экран — редактирование ОДНОГО сообщения (edit_message_text),
на каждом экране есть кнопки «⬅️ Назад» и/или «🏠 Меню» — пользователь ходит
по боту без набора команд и без простыни сообщений в чате.

callback_data кнопок:
    menu                         — главное меню (редактирует текущее сообщение)
    show:filters|premium|help    — экраны разделов
    toggle:pause                 — пауза/возобновление рассылки (из меню)
    flow:add                     — запустить конструктор фильтра
    flow:feedback                — оставить отзыв
    flow:tariffs                 — legacy-кнопка старых сообщений
    prop:room|apartment          — шаг 1 конструктора фильтра
    back:property | back:city    — «Назад» внутри конструктора
    city:<code>                  — шаг 2
    price:<число>|any            — шаг 3
    fdel:<id> / ftog:<id>        — удалить/выключить фильтр (обновляет список)
    pay:new                      — показать реквизиты
    paid:<payment_id>            — «Я оплатил»
    apay:<id> / rpay:<id>        — админ: подтвердить/отклонить платёж
"""

from __future__ import annotations

from datetime import datetime, timezone

from src import tariffs
from src.bot import texts
from src.cities import CITIES
from src.config import Config
from src.db import Database
from src.logging_setup import get_logger
from src.payments.base import PaymentProvider
from src.telegram import TelegramApi, inline_keyboard

logger = get_logger(__name__)

STATE_KEY_LAST_UPDATE = "last_update_id"

# Кнопки цен в конструкторе фильтра (BYN).
PRICE_BUTTONS = [300, 500, 800, 1000]


class Router:
    """Обработчик апдейтов бота."""

    def __init__(
        self,
        db: Database,
        api: TelegramApi,
        config: Config,
        provider: PaymentProvider,
    ) -> None:
        self._db = db
        self._api = api
        self._config = config
        self._provider = provider

    # --- основной цикл ---------------------------------------------------------

    def process_updates(self, poll_timeout: int = 0) -> int:
        """Забрать и обработать накопившиеся апдейты. Вернуть их число.

        poll_timeout > 0 включает long-polling: getUpdates держит соединение
        до poll_timeout секунд и возвращается мгновенно при новом сообщении.
        """
        last_id = self._db.get_state(STATE_KEY_LAST_UPDATE)
        offset = int(last_id) + 1 if last_id else None
        updates = self._api.get_updates(offset=offset, timeout=poll_timeout)
        if updates:
            logger.info("Апдейтов к обработке: %d (offset=%s)", len(updates), offset)

        for update in updates:
            update_id = update.get("update_id")
            try:
                self._handle_update(update)
            except Exception as exc:  # noqa: BLE001 — один апдейт не валит цикл
                logger.error("Ошибка обработки апдейта %s: %s", update_id, exc, exc_info=True)
            # Помечаем обработанным в любом случае — иначе «ядовитый» апдейт
            # зациклит бота навсегда.
            if update_id is not None:
                self._db.set_state(STATE_KEY_LAST_UPDATE, str(update_id))
        return len(updates)

    def _handle_update(self, update: dict) -> None:
        if "message" in update:
            self._handle_message(update["message"])
        elif "callback_query" in update:
            self._handle_callback(update["callback_query"])
        else:
            logger.debug("Апдейт неизвестного типа: %s", sorted(update))

    # --- сообщения ---------------------------------------------------------------

    def _handle_message(self, msg: dict) -> None:
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if chat_id is None or not text:
            logger.debug("Пропуск сообщения без chat_id/текста")
            return

        sender = msg.get("from") or {}
        user = self._db.upsert_user(chat_id, sender.get("username"), sender.get("first_name"))
        logger.info("Сообщение от chat_id=%s: %r", chat_id, text[:50])

        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
        if command == "/start":
            self._cmd_start(user)
        elif command == "/add":
            self._start_filter_flow(user)
        elif command == "/filters":
            self._cmd_filters(user)
        elif command == "/feedback":
            self._start_feedback(user)
        elif command == "/pause":
            self._db.update_user(chat_id, {"paused": True})
            self._api.send_message(chat_id, texts.PAUSED,
                                   reply_markup=inline_keyboard([self._nav_row()]))
        elif command == "/resume":
            self._db.update_user(chat_id, {"paused": False})
            self._api.send_message(chat_id, texts.RESUMED,
                                   reply_markup=inline_keyboard([self._nav_row()]))
        elif command == "/help":
            self._api.send_message(chat_id, texts.HELP,
                                   reply_markup=inline_keyboard([self._nav_row()]))
        elif command in ("/approve", "/reject", "/grant", "/stats", "/users"):
            self._handle_admin_command(user, command, text)
        elif command:
            self._api.send_message(chat_id, texts.UNKNOWN,
                                   reply_markup=inline_keyboard([self._nav_row()]))
        else:
            self._handle_plain_text(user, text)

    def _handle_plain_text(self, user: dict, text: str) -> None:
        """Текст вне команд: отзыв или цена, если юзер в соответствующем диалоге."""
        state = dict(user.get("dialog_state") or {})
        stage = state.get("stage")
        if stage == "feedback":
            self._save_feedback(user, text)
            return
        if stage != "price":
            self._api.send_message(user["chat_id"], texts.UNKNOWN,
                                   reply_markup=inline_keyboard([self._nav_row()]))
            return
        try:
            price = float(text.replace(",", ".").strip())
            if price <= 0:
                raise ValueError
        except ValueError:
            self._api.send_message(user["chat_id"], texts.PRICE_NOT_A_NUMBER)
            return
        self._save_filter(user, state, price)

    # --- callback-кнопки -----------------------------------------------------------

    def _handle_callback(self, cq: dict) -> None:
        data = cq.get("data") or ""
        msg = cq.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")
        cq_id = cq.get("id")
        if chat_id is None:
            logger.debug("callback_query без message.chat — пропуск")
            return

        sender = cq.get("from") or {}
        user = self._db.upsert_user(chat_id, sender.get("username"), sender.get("first_name"))
        logger.info("Кнопка от chat_id=%s: %r", chat_id, data)

        action, _, arg = data.partition(":")
        handlers = {
            "menu": self._cb_menu,
            "show": self._cb_show,
            "toggle": self._cb_toggle,
            "back": self._cb_back,
            "flow": self._cb_flow,
            "prop": self._cb_property,
            "city": self._cb_city,
            "price": self._cb_price,
            "fdel": self._cb_filter_delete,
            "ftog": self._cb_filter_toggle,
            "pay": self._cb_pay,
            "paid": self._cb_paid,
            "apay": self._cb_admin_payment_confirm,
            "rpay": self._cb_admin_payment_reject,
        }
        handler = handlers.get(action)
        if handler is None:
            logger.warning("Неизвестная кнопка: %r", data)
        else:
            handler(user, arg, message_id)
        if cq_id:
            self._api.answer_callback_query(cq_id)

    # --- главное меню и экраны ---------------------------------------------------------

    def _nav_row(self, back_to: str | None = None) -> list[tuple[str, str]]:
        """Нижний ряд навигации: опционально «Назад» + всегда «Меню»."""
        row = []
        if back_to:
            row.append(("⬅️ Назад", f"back:{back_to}"))
        row.append(("🏠 Меню", "menu"))
        return row

    def _show_menu(self, user: dict, message_id: int | None = None) -> None:
        """Главное меню: тариф, статус рассылки, все действия кнопками."""
        now = datetime.now(timezone.utc)
        tariff = tariffs.effective_tariff(user, now)
        paid_until = tariffs.parse_dt(user.get("paid_until"))
        tariff_line = texts.fmt_tariff_line(
            tariff, paid_until.strftime("%d.%m.%Y") if paid_until else None
        )
        paused = bool(user.get("paused"))
        pause_label = "▶️ Возобновить рассылку" if paused else "⏸ Пауза рассылки"
        kb = inline_keyboard([
            [("🔎 Новый фильтр", "flow:add")],
            [("📋 Мои фильтры", "show:filters")],
            [("💬 Отзыв", "flow:feedback"), ("ℹ️ Помощь", "show:help")],
            [(pause_label, "toggle:pause")],
        ])
        logger.debug("[FIX] Экран меню: chat_id=%s (edit=%s)", user["chat_id"], bool(message_id))
        self._edit_or_send(user["chat_id"], message_id,
                           texts.fmt_menu(tariff_line, paused), kb)

    def _cmd_start(self, user: dict) -> None:
        self._db.update_user(user["chat_id"], {"dialog_state": {}})
        kb = inline_keyboard([
            [("🔎 Настроить фильтр", "flow:add")],
            [("📋 Мои фильтры", "show:filters")],
            [("💬 Отзыв", "flow:feedback"), ("ℹ️ Помощь", "show:help")],
        ])
        self._api.send_message(user["chat_id"], texts.fmt_welcome(user.get("first_name")),
                               reply_markup=kb)

    def _cb_menu(self, user: dict, arg: str, message_id: int | None) -> None:
        self._db.update_user(user["chat_id"], {"dialog_state": {}})
        self._show_menu(user, message_id)

    def _cb_show(self, user: dict, arg: str, message_id: int | None) -> None:
        if arg == "filters":
            self._show_filters(user, message_id)
        elif arg == "premium":
            self._show_premium(user, message_id)
        elif arg == "help":
            self._edit_or_send(user["chat_id"], message_id, texts.HELP,
                               inline_keyboard([self._nav_row()]))

    def _cb_toggle(self, user: dict, arg: str, message_id: int | None) -> None:
        if arg != "pause":
            return
        new_paused = not bool(user.get("paused"))
        self._db.update_user(user["chat_id"], {"paused": new_paused})
        logger.info("[FIX] Пауза=%s через меню: chat_id=%s", new_paused, user["chat_id"])
        self._show_menu(self._db.get_user(user["chat_id"]), message_id)

    def _cb_flow(self, user: dict, arg: str, message_id: int | None) -> None:
        if arg == "add":
            self._start_filter_flow(user, message_id)
        elif arg == "feedback":
            self._start_feedback(user, message_id)
        elif arg == "tariffs":  # legacy-кнопка старых сообщений
            self._show_premium(user, message_id)

    # --- конструктор фильтра -----------------------------------------------------------

    def _start_filter_flow(self, user: dict, message_id: int | None = None) -> None:
        now = datetime.now(timezone.utc)
        tariff = tariffs.effective_tariff(user, now)
        limit = tariffs.filter_limit(tariff, self._config.premium_max_filters)
        existing = self._db.get_user_filters(user["id"])
        if len(existing) >= limit:
            text = texts.fmt_filter_limit(limit)
            rows = [[("📋 Мои фильтры", "show:filters")], self._nav_row()]
            self._edit_or_send(user["chat_id"], message_id, text, inline_keyboard(rows))
            logger.debug("Лимит фильтров: chat_id=%s (%d/%d, %s)",
                         user["chat_id"], len(existing), limit, tariff)
            return
        self._show_property_screen(user, message_id)

    def _show_property_screen(self, user: dict, message_id: int | None) -> None:
        """Шаг 1: тип жилья. «Назад» отсюда — в меню."""
        self._db.update_user(user["chat_id"], {"dialog_state": {"stage": "property"}})
        kb = inline_keyboard([
            [("🛏 Комната", "prop:room"), ("🏢 Квартира", "prop:apartment")],
            self._nav_row(),
        ])
        self._edit_or_send(user["chat_id"], message_id, texts.CHOOSE_PROPERTY, kb)

    def _show_city_screen(self, user: dict, state: dict, message_id: int | None) -> None:
        """Шаг 2: город. «Назад» — к выбору типа жилья."""
        self._db.update_user(user["chat_id"], {"dialog_state": state})
        rows, row = [], []
        for city in CITIES:
            row.append((city.name, f"city:{city.code}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append(self._nav_row(back_to="property"))
        self._edit_or_send(user["chat_id"], message_id, texts.CHOOSE_CITY, inline_keyboard(rows))

    def _show_price_screen(self, user: dict, state: dict, message_id: int | None) -> None:
        """Шаг 3: цена. «Назад» — к выбору города."""
        self._db.update_user(user["chat_id"], {"dialog_state": state})
        rows = [
            [(f"до {PRICE_BUTTONS[0]}", f"price:{PRICE_BUTTONS[0]}"),
             (f"до {PRICE_BUTTONS[1]}", f"price:{PRICE_BUTTONS[1]}")],
            [(f"до {PRICE_BUTTONS[2]}", f"price:{PRICE_BUTTONS[2]}"),
             (f"до {PRICE_BUTTONS[3]}", f"price:{PRICE_BUTTONS[3]}")],
            [(texts.PRICE_ANY_LABEL, "price:any")],
            self._nav_row(back_to="city"),
        ]
        self._edit_or_send(user["chat_id"], message_id, texts.CHOOSE_PRICE, inline_keyboard(rows))

    def _cb_back(self, user: dict, arg: str, message_id: int | None) -> None:
        """«Назад» в конструкторе: возврат на предыдущий шаг с сохранением выбора."""
        state = dict(user.get("dialog_state") or {})
        logger.debug("[FIX] Назад к %s: chat_id=%s state=%s", arg, user["chat_id"], state)
        if arg == "property":
            self._show_property_screen(user, message_id)
        elif arg == "city":
            state.pop("city_code", None)
            state["stage"] = "city"
            if not state.get("property_type"):
                self._show_property_screen(user, message_id)
                return
            self._show_city_screen(user, state, message_id)

    def _cb_property(self, user: dict, arg: str, message_id: int | None) -> None:
        if arg not in ("room", "apartment"):
            return
        self._show_city_screen(user, {"stage": "city", "property_type": arg}, message_id)

    def _cb_city(self, user: dict, arg: str, message_id: int | None) -> None:
        state = dict(user.get("dialog_state") or {})
        if state.get("stage") != "city" or arg not in {c.code for c in CITIES}:
            logger.debug("city вне диалога: chat_id=%s stage=%s", user["chat_id"], state.get("stage"))
            return
        state.update({"stage": "price", "city_code": arg})
        self._show_price_screen(user, state, message_id)

    def _cb_price(self, user: dict, arg: str, message_id: int | None) -> None:
        state = dict(user.get("dialog_state") or {})
        if state.get("stage") != "price":
            return
        max_price = None if arg == "any" else float(arg)
        self._save_filter(user, state, max_price, message_id=message_id)

    def _save_filter(self, user: dict, state: dict, max_price: float | None,
                     message_id: int | None = None) -> None:
        property_type = state.get("property_type")
        city_code = state.get("city_code")
        if not property_type or not city_code:
            logger.warning("Неполное состояние диалога у chat_id=%s: %s", user["chat_id"], state)
            self._db.update_user(user["chat_id"], {"dialog_state": {}})
            self._show_menu(user, message_id)
            return
        self._db.add_filter(user["id"], property_type, city_code, max_price)
        self._db.update_user(user["chat_id"], {"dialog_state": {}})
        kb = inline_keyboard([
            [("➕ Ещё фильтр", "flow:add")],
            [("📋 Мои фильтры", "show:filters")],
            self._nav_row(),
        ])
        self._edit_or_send(user["chat_id"], message_id,
                           texts.fmt_filter_saved(property_type, city_code, max_price), kb)

    # --- мои фильтры ---------------------------------------------------------------------

    def _show_filters(self, user: dict, message_id: int | None = None) -> None:
        """Экран «Мои фильтры»: список + управление, обновляется на месте."""
        filters = self._db.get_user_filters(user["id"])
        if not filters:
            kb = inline_keyboard([[("🔎 Новый фильтр", "flow:add")], self._nav_row()])
            self._edit_or_send(user["chat_id"], message_id, texts.NO_FILTERS, kb)
            return
        lines = [texts.FILTERS_HEADER, ""]
        rows = []
        for i, f in enumerate(filters, start=1):
            lines.append(f"{i}. {texts.fmt_filter_line(f)}")
            toggle_label = f"▶️ Включить {i}" if not f.get("enabled", True) else f"⏸ Выключить {i}"
            rows.append([(f"🗑 Удалить {i}", f"fdel:{f['id']}"), (toggle_label, f"ftog:{f['id']}")])
        rows.append([("➕ Добавить", "flow:add")])
        rows.append(self._nav_row())
        self._edit_or_send(user["chat_id"], message_id, "\n".join(lines),
                           inline_keyboard(rows))

    def _cmd_filters(self, user: dict) -> None:
        self._show_filters(user)

    def _cb_filter_delete(self, user: dict, arg: str, message_id: int | None) -> None:
        if self._filter_owned(user, arg):
            self._db.delete_filter(int(arg))
            logger.info("[FIX] Фильтр %s удалён кнопкой: chat_id=%s", arg, user["chat_id"])
            # Обновляем список на месте — пользователь сразу видит результат.
            self._show_filters(user, message_id)

    def _cb_filter_toggle(self, user: dict, arg: str, message_id: int | None) -> None:
        f = self._filter_owned(user, arg)
        if f:
            new_enabled = not f.get("enabled", True)
            self._db.set_filter_enabled(int(arg), new_enabled)
            logger.info("[FIX] Фильтр %s -> enabled=%s: chat_id=%s",
                        arg, new_enabled, user["chat_id"])
            self._show_filters(user, message_id)

    def _filter_owned(self, user: dict, arg: str) -> dict | None:
        """Фильтр по id, только если принадлежит юзеру (защита от чужих id)."""
        try:
            filter_id = int(arg)
        except ValueError:
            return None
        f = next((f for f in self._db.get_user_filters(user["id"]) if f["id"] == filter_id), None)
        if f is None:
            logger.warning("chat_id=%s пытался управлять чужим фильтром %s",
                           user["chat_id"], arg)
        return f

    # --- отзывы -------------------------------------------------------------------------

    def _start_feedback(self, user: dict, message_id: int | None = None) -> None:
        """Показать приглашение к отзыву и перевести диалог в стадию 'feedback'."""
        self._db.update_user(user["chat_id"], {"dialog_state": {"stage": "feedback"}})
        self._edit_or_send(user["chat_id"], message_id, texts.FEEDBACK_PROMPT,
                           inline_keyboard([self._nav_row()]))

    def _save_feedback(self, user: dict, text: str) -> None:
        """Сохранить отзыв, подтвердить пользователю и переслать администратору."""
        self._db.add_feedback(user["id"], user["chat_id"], user.get("username"), text)
        self._db.update_user(user["chat_id"], {"dialog_state": {}})
        logger.info("[FIX] Отзыв от chat_id=%s: %r", user["chat_id"], text[:80])
        self._api.send_message(user["chat_id"], texts.FEEDBACK_SAVED,
                               reply_markup=inline_keyboard([self._nav_row()]))
        if self._config.admin_chat_id:
            self._api.send_message(
                self._config.admin_chat_id,
                texts.fmt_admin_new_feedback(user["chat_id"], user.get("username"), text),
            )
        else:
            logger.warning("ADMIN_CHAT_ID не задан — отзыв некому переслать (сохранён в БД)")

    # --- премиум и оплата -----------------------------------------------------------------

    def _show_premium(self, user: dict, message_id: int | None = None) -> None:
        """Экран «Премиум»: оффер с оплатой либо статус активной подписки."""
        now = datetime.now(timezone.utc)
        if tariffs.effective_tariff(user, now) == tariffs.TARIFF_PREMIUM:
            kb = inline_keyboard([[("📋 Мои фильтры", "show:filters")], self._nav_row()])
            self._edit_or_send(user["chat_id"], message_id, texts.ALREADY_PREMIUM, kb)
            return
        kb = inline_keyboard([[("💳 Оплатить", "pay:new")], self._nav_row()])
        self._edit_or_send(
            user["chat_id"], message_id,
            texts.fmt_premium_offer(self._config.tariff_price_byn,
                                    self._config.premium_max_filters),
            kb,
        )

    def _cmd_premium(self, user: dict) -> None:
        self._show_premium(user)

    def _cb_pay(self, user: dict, arg: str, message_id: int | None) -> None:
        amount = self._config.tariff_price_byn
        invoice = self._provider.create_invoice(user["chat_id"], amount, "BYN")
        payment = self._db.create_payment(
            user["id"], amount, "BYN", self._provider.name, invoice.order_id
        )
        kb = inline_keyboard([
            [("Я оплатил ✅", f"paid:{payment['id']}")],
            self._nav_row(),
        ])
        # Реквизиты — новым сообщением: они должны остаться в чате у пользователя,
        # а не быть затёртыми следующим переходом по меню.
        self._api.send_message(user["chat_id"], invoice.message_text, reply_markup=kb)

    def _cb_paid(self, user: dict, arg: str, message_id: int | None) -> None:
        payment = self._db.get_payment(int(arg)) if arg.isdigit() else None
        if payment is None or payment["user_id"] != user["id"]:
            logger.warning("paid: чужой/несуществующий платёж %r от chat_id=%s",
                           arg, user["chat_id"])
            return
        if payment["status"] != "pending":
            logger.debug("paid: платёж %s уже в статусе %s", arg, payment["status"])
            return
        self._api.send_message(user["chat_id"], texts.PAYMENT_PENDING)
        if self._config.admin_chat_id:
            kb = inline_keyboard([[
                ("✅ Подтвердить", f"apay:{payment['id']}"),
                ("❌ Отклонить", f"rpay:{payment['id']}"),
            ]])
            self._api.send_message(
                self._config.admin_chat_id,
                texts.fmt_admin_new_payment(
                    payment["id"], user["chat_id"], user.get("username"),
                    float(payment["amount"]), payment["currency"], payment["order_id"],
                ),
                reply_markup=kb,
            )
        else:
            logger.warning("ADMIN_CHAT_ID не задан — заявку на оплату некому подтвердить!")

    # --- админ ------------------------------------------------------------------------------

    def _is_admin(self, user: dict) -> bool:
        is_admin = user.get("is_admin") or (
            self._config.admin_chat_id
            and str(user["chat_id"]) == str(self._config.admin_chat_id)
        )
        if not is_admin:
            logger.warning("Не-админ chat_id=%s вызвал админ-действие", user["chat_id"])
        return bool(is_admin)

    def _handle_admin_command(self, user: dict, command: str, text: str) -> None:
        if not self._is_admin(user):
            self._api.send_message(user["chat_id"], texts.NOT_ADMIN)
            return
        args = text.split()[1:]
        if command == "/stats":
            c = self._db.counts()
            self._api.send_message(user["chat_id"], texts.fmt_stats(
                c["total_users"], c["premium_users"], c["active_filters"],
                c["pending_payments"], c["deliveries_24h"],
            ))
        elif command == "/users":
            users = self._db.list_users()
            total = self._db.counts()["total_users"]
            logger.info("[FIX] /users: админ chat_id=%s запросил список (%d)",
                        user["chat_id"], total)
            self._api.send_message(user["chat_id"], texts.fmt_users_list(users, total))
        elif command == "/approve" and args:
            self._confirm_payment(user, args[0])
        elif command == "/reject" and args:
            self._reject_payment(user, args[0])
        elif command == "/grant" and len(args) >= 2:
            self._grant(user, args[0], args[1])
        else:
            self._api.send_message(
                user["chat_id"],
                "Использование: /approve &lt;id&gt; · /reject &lt;id&gt; · "
                "/grant &lt;chat_id&gt; &lt;дней&gt; · /stats · /users",
            )

    def _cb_admin_payment_confirm(self, user: dict, arg: str, message_id: int | None) -> None:
        if self._is_admin(user):
            self._confirm_payment(user, arg)

    def _cb_admin_payment_reject(self, user: dict, arg: str, message_id: int | None) -> None:
        if self._is_admin(user):
            self._reject_payment(user, arg)

    def _confirm_payment(self, admin: dict, arg: str) -> None:
        payment = self._db.get_payment(int(arg)) if str(arg).isdigit() else None
        if payment is None:
            self._api.send_message(admin["chat_id"], f"Платёж {arg} не найден.")
            return
        if payment["status"] != "pending":
            self._api.send_message(
                admin["chat_id"], f"Платёж {arg} уже в статусе {payment['status']}."
            )
            return
        now = datetime.now(timezone.utc)
        self._db.set_payment_status(payment["id"], "confirmed", now)
        payer = self._db.get_user_by_id(payment["user_id"])
        if payer is None:
            logger.error("Платёж %s: пользователь id=%s не найден", arg, payment["user_id"])
            return
        paid_until = tariffs.activate_premium(self._db, payer, now=now)
        self._api.send_message(
            payer["chat_id"], texts.fmt_payment_confirmed(paid_until.strftime("%d.%m.%Y"))
        )
        self._api.send_message(
            admin["chat_id"],
            f"✅ Платёж {payment['id']} подтверждён, премиум до "
            f"{paid_until.strftime('%d.%m.%Y')} у chat_id={payer['chat_id']}.",
        )

    def _reject_payment(self, admin: dict, arg: str) -> None:
        payment = self._db.get_payment(int(arg)) if str(arg).isdigit() else None
        if payment is None or payment["status"] != "pending":
            self._api.send_message(admin["chat_id"], f"Платёж {arg} не найден или уже обработан.")
            return
        self._db.set_payment_status(payment["id"], "rejected", None)
        payer = self._db.get_user_by_id(payment["user_id"])
        if payer is not None:
            self._api.send_message(payer["chat_id"], texts.PAYMENT_REJECTED)
        self._api.send_message(admin["chat_id"], f"❌ Платёж {payment['id']} отклонён.")

    def _grant(self, admin: dict, chat_id_arg: str, days_arg: str) -> None:
        try:
            chat_id, days = int(chat_id_arg), int(days_arg)
        except ValueError:
            self._api.send_message(admin["chat_id"], "Использование: /grant <chat_id> <дней>")
            return
        target = self._db.get_user(chat_id)
        if target is None:
            self._api.send_message(admin["chat_id"], f"Пользователь {chat_id} не найден.")
            return
        paid_until = tariffs.activate_premium(self._db, target, days=days)
        self._api.send_message(
            target["chat_id"], texts.fmt_payment_confirmed(paid_until.strftime("%d.%m.%Y"))
        )
        self._api.send_message(
            admin["chat_id"],
            f"✅ Премиум выдан chat_id={chat_id} до {paid_until.strftime('%d.%m.%Y')}.",
        )

    # --- утилиты ---------------------------------------------------------------------------

    def _edit_or_send(self, chat_id: int, message_id: int | None, text: str,
                      reply_markup: dict | None) -> None:
        """Редактировать сообщение меню (плавный диалог) или отправить новое."""
        if message_id is not None:
            result = self._api.edit_message_text(chat_id, message_id, text,
                                                 reply_markup=reply_markup)
            if result is not None:
                return
        self._api.send_message(chat_id, text, reply_markup=reply_markup)
