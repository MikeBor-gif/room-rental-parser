"""Все тексты бота в одном модуле (HTML, parse_mode=HTML).

Правила: короткие абзацы, эмодзи как маркеры, цены и лимиты — подстановкой
из конфига (не хардкодить в текстах). Динамические тексты — функции fmt_*.
"""

from __future__ import annotations

from src.cities import CITY_BY_CODE

# --- справочные подписи -------------------------------------------------------

PROPERTY_LABELS = {"room": "Комната", "apartment": "Квартира"}


def city_name(city_code: str) -> str:
    city = CITY_BY_CODE.get(city_code)
    return city.name if city else city_code


# --- /start и справка -----------------------------------------------------------

def fmt_welcome(first_name: str | None) -> str:
    hello = f"Привет, {first_name}!" if first_name else "Привет!"
    return (
        f"👋 <b>{hello}</b>\n\n"
        "Я слежу за <b>Kufar, Onliner и Realt</b> и присылаю новые объявления "
        "об аренде <b>комнат и квартир</b> раньше, чем их увидит большинство.\n\n"
        "🏙 Города: Минск, Брест, Витебск, Гомель, Гродно, Могилёв\n"
        "🔎 Фильтры: тип жилья, город, максимальная цена\n"
        "📸 Карточки с фото и прямой ссылкой\n\n"
        "Настроим первый фильтр? Это займёт 20 секунд.\n\n"
        "⏳ <i>Я отвечаю с задержкой до пары минут — так устроен мой хостинг. "
        "Зато объявления присылаю круглосуточно!</i>"
    )


HELP = (
    "ℹ️ <b>Как пользоваться ботом</b>\n\n"
    "Всё управление — кнопками, команды набирать не нужно. "
    "Главное меню всегда доступно по кнопке «🏠 Меню» или команде /start.\n\n"
    "🔎 <b>Новый фильтр</b> — что искать: комната/квартира → город → цена\n"
    "📋 <b>Мои фильтры</b> — список, включение/выключение, удаление\n"
    "⭐ <b>Премиум</b> — мгновенные уведомления и до 5 фильтров\n"
    "⏸ <b>Пауза</b> — временно остановить рассылку (фильтры сохраняются)\n\n"
    "Команды-дублёры: /start /add /filters /premium /pause /resume /help"
)


def fmt_menu(tariff_line: str, paused: bool) -> str:
    status = "⏸ Рассылка на паузе" if paused else "▶️ Рассылка активна"
    return (
        "🏠 <b>Главное меню</b>\n\n"
        f"{tariff_line}\n"
        f"{status}\n\n"
        "Выберите действие:"
    )


def fmt_tariff_line(tariff: str, paid_until_str: str | None) -> str:
    if tariff == "premium" and paid_until_str:
        return f"⭐ Тариф: <b>Премиум</b> до {paid_until_str}"
    return "🆓 Тариф: <b>Бесплатный</b>"

UNKNOWN = (
    "🤔 Не понял команду. Попробуйте /help — там список всего, что я умею."
)

PAUSED = "⏸ Рассылка приостановлена. Вернуть: /resume"
RESUMED = "▶️ Рассылка возобновлена! Пришлю всё новое по вашим фильтрам."


# --- тарифы ---------------------------------------------------------------------

def fmt_tariffs(price_byn: float, free_batch_minutes: int, premium_max_filters: int) -> str:
    return (
        "💼 <b>Тарифы</b>\n\n"
        "🆓 <b>Бесплатный</b>\n"
        f"  • 1 фильтр\n"
        f"  • подборка новых объявлений раз в ~{free_batch_minutes} минут\n\n"
        f"⭐ <b>Премиум — {price_byn:.0f} BYN / 30 дней</b>\n"
        f"  • до {premium_max_filters} фильтров\n"
        "  • объявления сразу после появления (каждые 2–4 минуты)\n"
        "  • на горячем рынке аренды скорость решает: лучшие варианты "
        "разбирают за часы\n\n"
        "Оформить: /premium"
    )


def fmt_premium_offer(price_byn: float, premium_max_filters: int) -> str:
    return (
        f"⭐ <b>Премиум — {price_byn:.0f} BYN / 30 дней</b>\n\n"
        f"• До {premium_max_filters} фильтров (можно следить и за комнатами, и за квартирами "
        "в разных городах)\n"
        "• Мгновенные уведомления — объявления приходят через 2–4 минуты после публикации\n\n"
        "Нажмите «Оплатить», чтобы получить реквизиты."
    )


def fmt_payment_instructions(price_byn: float, payment_details: str, order_id: str) -> str:
    details = payment_details or "Реквизиты уточняются — напишите администратору."
    return (
        f"💳 <b>Оплата премиума — {price_byn:.0f} BYN</b>\n\n"
        f"{details}\n\n"
        f"🧾 Код платежа: <code>{order_id}</code>\n"
        "(укажите его в комментарии к переводу, если возможно)\n\n"
        "После оплаты нажмите кнопку «Я оплатил ✅» — я передам заявку на проверку. "
        "Подтверждение обычно занимает не больше пары часов."
    )


PAYMENT_PENDING = (
    "🕐 Заявка на проверке!\n\n"
    "Как только администратор подтвердит оплату, премиум включится автоматически, "
    "и я пришлю сообщение. Обычно это занимает не больше пары часов."
)

def fmt_payment_confirmed(paid_until: str) -> str:
    return (
        "🎉 <b>Премиум активирован!</b>\n\n"
        f"Подписка действует до <b>{paid_until}</b>.\n"
        "Теперь объявления приходят мгновенно, фильтров — до 5 штук: /add"
    )


PAYMENT_REJECTED = (
    "😔 Оплата не подтверждена.\n\n"
    "Если вы уверены, что перевод прошёл — свяжитесь с администратором "
    "или попробуйте ещё раз: /premium"
)

ALREADY_PREMIUM = "⭐ У вас уже активен премиум! Посмотреть фильтры: /filters"


def fmt_subscription_expiring(days_left: int) -> str:
    return (
        f"⏰ Премиум закончится через <b>{days_left} дн.</b>\n\n"
        "Продлить, чтобы не пропустить лучшие варианты: /premium"
    )


SUBSCRIPTION_EXPIRED = (
    "💤 Премиум-подписка закончилась — вы переведены на бесплатный тариф "
    "(1 фильтр, подборки раз в полчаса).\n\n"
    "Вернуть мгновенные уведомления: /premium"
)


# --- конструктор фильтра --------------------------------------------------------

CHOOSE_PROPERTY = "🏠 <b>Что ищем?</b>"
CHOOSE_CITY = "🏙 <b>В каком городе?</b>"
CHOOSE_PRICE = (
    "💰 <b>Максимальная цена (BYN в месяц)?</b>\n\n"
    "Выберите вариант или отправьте своё число сообщением."
)
PRICE_ANY_LABEL = "Не важно"

PRICE_NOT_A_NUMBER = (
    "Не похоже на число 🙂 Отправьте цену цифрами (например, <b>600</b>) "
    "или нажмите кнопку «Не важно»."
)


def fmt_filter_saved(property_type: str, city_code: str, max_price: float | None) -> str:
    price = f"до {max_price:.0f} BYN" if max_price else "любая цена"
    return (
        "✅ <b>Фильтр сохранён!</b>\n\n"
        f"🔎 {PROPERTY_LABELS.get(property_type, property_type)} · "
        f"{city_name(city_code)} · {price}\n\n"
        "Теперь я слежу за новыми объявлениями по этому фильтру. "
        "Как только появится подходящее — пришлю карточку с фото."
    )


def fmt_filter_limit_free(price_byn: float) -> str:
    return (
        "🚧 На бесплатном тарифе доступен <b>1 фильтр</b>.\n\n"
        f"⭐ Премиум ({price_byn:.0f} BYN/мес) — до 5 фильтров и мгновенные "
        "уведомления.\n\n"
        "Либо удалите текущий фильтр и создайте новый."
    )


def fmt_filter_limit_premium(max_filters: int) -> str:
    return (
        f"🚧 Достигнут лимит: {max_filters} фильтров.\n"
        "Удалите ненужный, чтобы добавить новый."
    )


# --- список фильтров ------------------------------------------------------------

NO_FILTERS = "У вас пока нет фильтров. Создать первый: /add"


def fmt_filter_line(f: dict) -> str:
    price = f"до {float(f['max_price']):.0f} BYN" if f.get("max_price") else "любая цена"
    status = "" if f.get("enabled", True) else " (⏸ выключен)"
    return (
        f"{PROPERTY_LABELS.get(f['property_type'], f['property_type'])} · "
        f"{city_name(f['city_code'])} · {price}{status}"
    )


FILTERS_HEADER = "🔎 <b>Ваши фильтры</b>\n\nНажмите на фильтр, чтобы удалить или выключить его."
FILTER_DELETED = "🗑 Фильтр удалён."
FILTER_TOGGLED_ON = "▶️ Фильтр включён."
FILTER_TOGGLED_OFF = "⏸ Фильтр выключен."


# --- админ ----------------------------------------------------------------------

def fmt_admin_new_payment(payment_id: int, chat_id: int, username: str | None,
                          amount: float, currency: str, order_id: str) -> str:
    user = f"@{username}" if username else f"chat_id={chat_id}"
    return (
        f"💰 <b>Новая заявка на оплату #{payment_id}</b>\n\n"
        f"От: {user}\n"
        f"Сумма: {amount:.0f} {currency}\n"
        f"Код платежа: <code>{order_id}</code>\n\n"
        "Проверьте поступление и подтвердите или отклоните."
    )


NOT_ADMIN = "⛔ Эта команда доступна только администратору."


def fmt_stats(total_users: int, premium_users: int, active_filters: int,
              pending_payments: int, deliveries_24h: int) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users} (премиум: {premium_users})\n"
        f"🔎 Активных фильтров: {active_filters}\n"
        f"💰 Платежей на проверке: {pending_payments}\n"
        f"📨 Доставок за 24 ч: {deliveries_24h}"
    )
