# Telegram-бот аренды: комнаты и квартиры Беларуси

Бот следит за **Kufar, Onliner и Realt** и присылает пользователям новые
объявления об аренде **комнат и квартир** по их фильтрам (город, тип жилья,
цена) — с фото и прямой ссылкой. Инфраструктура бесплатная: GitHub Actions +
cron-job.org + Supabase.

**Города:** Минск, Брест, Витебск, Гомель, Гродно, Могилёв.

## Тариф

Бесплатный тариф — единственный:

| 🆓 Бесплатный |
|---|
| до 5 фильтров |
| подборка новых объявлений раз в ~5 минут |
| канал обратной связи: кнопка «💬 Отзыв» / команда `/feedback` |

Премиум-подписка временно отключена (убрана из интерфейса), но её код
оставлен дормантным: интерфейс `PaymentProvider` (manual + каркас
bepaid/Express-Pay), `activate_premium`, админ-подтверждение платежей —
всё на месте и легко включается обратно.

## Архитектура

```
Пользователь ⇄ Telegram Bot API
                   ▲
                   │
┌──────────────────┴───────────────────────────────────────────┐
│ GitHub Actions (дёргается cron-job.org через workflow_dispatch)│
│                                                                │
│  bot.yml (~5 мин): getUpdates → роутер → меню, фильтры,        │
│                    отзывы, админ-команды                       │
│  scrape.yml (~5 мин): парсеры → новые объявления → матчинг     │
│                    по фильтрам → доставка (фото + ссылка)      │
└──────────────────┬────────────────────────────────────────────┘
                   ▼
     Supabase (Postgres) — пользователи, фильтры, объявления,
     очередь доставки, отзывы, платежи. Table Editor = готовая админка.
```

## Чек-лист запуска

1. **Supabase** — создать проект и таблицы: [docs/supabase-setup.md](docs/supabase-setup.md)
2. **Секреты GitHub** и **cron-job.org** (2 задания): [docs/deploy.md](docs/deploy.md)
3. **Оформление бота** в @BotFather: [docs/bot-setup.md](docs/bot-setup.md)
4. Написать боту `/start` и настроить первый фильтр 🎉

## Структура проекта

```
parser/
├── .github/workflows/
│   ├── bot.yml            # обработка команд/кнопок (лёгкий, ~5 мин)
│   └── scrape.yml         # парсинг + рассылка (~5 мин)
├── deploy/supabase_schema.sql  # схема БД (выполнить в SQL Editor)
├── docs/                  # инструкции: supabase, деплой, botfather
├── src/
│   ├── jobs/
│   │   ├── updates.py     # точка входа bot.yml
│   │   └── scrape.py      # точка входа scrape.yml
│   ├── bot/
│   │   ├── router.py      # команды, кнопки, диалоги, админка
│   │   └── texts.py       # все тексты бота
│   ├── parsers/           # kufar / onliner / realt (комнаты + квартиры)
│   ├── payments/          # PaymentProvider: manual (готов), bepaid (каркас)
│   ├── cities.py          # справочник городов + классификация объявлений
│   ├── db.py              # слой Supabase + FakeDatabase для тестов
│   ├── matching.py        # объявление × фильтры → доставки
│   ├── delivery.py        # отправка: free батчем (раз в ~5 мин)
│   ├── tariffs.py         # лимиты фильтров, подписка (премиум дормантный)
│   ├── telegram.py        # Telegram Bot API клиент
│   └── main.py            # локальный запуск / режим демона (VM)
└── tests/                 # pytest: 94 теста
```

## Локальный запуск

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env                              # заполнить значения
python -m pytest -q                               # тесты
python -m src.main                                # один полный прогон
```

Режим демона на своей машине/VPS (вместо GitHub Actions):
`POLL_INTERVAL_SECONDS=120 python -m src.main` — и cron-job.org не нужен.

## Как добавить город

Одна запись в `src/cities.py` (код, имя, хэштег, координатная рамка) —
парсеры и меню бота подхватят её автоматически.

## Как добавить сайт-источник

Новый класс в `src/parsers/` по образцу `example_site.py`, регистрация
в `PARSER_CLASSES` (`src/jobs/scrape.py`). Интерфейс: `fetch() -> list[Listing]`.
