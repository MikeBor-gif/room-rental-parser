# План: Telegram-бот с тарифами — комнаты и квартиры по городам Беларуси

**Дата создания:** 2026-07-14
**Режим:** full
**Ветка:** `feature/telegram-bot-tariffs`
**База:** существующий парсер комнат (Минск) с рассылкой в один чат через GitHub Actions

## Настройки

- **Тесты:** да (тарифы, матчинг фильтров, роутер бота, парсеры квартир на фикстурах, платёжная логика)
- **Логирование:** подробное (DEBUG для разработки, через `LOG_LEVEL`)
- **Документация:** да — обязательный чекпойнт (README-инструкции по настройке Supabase, секретов, cron-job.org, BotFather)

## Roadmap Linkage

- Milestone: "none"
- Rationale: ROADMAP.md отсутствует в проекте

## Целевой продукт

Пользователь заходит в бота → `/start` → выбирает тариф → настраивает фильтр
(комната/квартира → город → макс. цена) → оплачивает (если премиум) → получает
объявления с фото по своим фильтрам, пока действует подписка.

### Тарифы (цены — конфигурируемые, не хардкод)

| | Бесплатный | Премиум (15 BYN/мес) |
|---|---|---|
| Фильтров | 1 | до 5 |
| Частота уведомлений | раз в ~30 мин (батч) | каждый прогон (~2–4 мин) |
| Типы жилья | комнаты и квартиры | комнаты и квартиры |

### Города (старт): Минск, Брест, Витебск, Гомель, Гродно, Могилёв

Справочник городов — один файл, добавление города = одна запись.

## Архитектура

```
Пользователь ⇄ Telegram Bot API
                   ▲
                   │ getUpdates / sendMessage / sendPhoto
                   │
┌──────────────────┴───────────────────────────────────────────┐
│ GitHub Actions (запуск с cron-job.org через workflow_dispatch)│
│                                                               │
│  bot.yml (каждую ~1 мин, лёгкий: только httpx+supabase)       │
│    └─ src/jobs/updates.py: getUpdates → роутер → ответы,      │
│       регистрация, фильтры, тарифы, «Я оплатил», админ-команды│
│                                                               │
│  scrape.yml (каждые ~2–3 мин)                                 │
│    └─ src/jobs/scrape.py: парсеры (вся Беларусь) → новые      │
│       listings → матчинг по фильтрам юзеров → deliveries →    │
│       отправка (премиум сразу, free батчем раз в 30 мин)      │
└──────────────────┬───────────────────────────────────────────┘
                   │ supabase-py (REST)
                   ▼
            Supabase (Postgres, free tier) = БД + веб-админка
```

**Ключевые решения:**

1. **Два workflow вместо одного.** `bot.yml` лёгкий (без bs4/lxml, только httpx+supabase,
   pip-кэш) — отвечает на команды за ~40–90 сек вместо 2–4 мин. `scrape.yml` — тяжёлый цикл
   парсинга. Независимые concurrency-группы. **Только `bot.yml` вызывает `getUpdates`** —
   Telegram допускает один активный getUpdates на бота (иначе 409 Conflict);
   `cancel-in-progress: true` в его concurrency-группе гарантирует отсутствие параллельных вызовов.
2. **Парсим всю Беларусь одним запросом на сайт/тип** (без rgn у Kufar, широкая рамка Onliner,
   общая лента Realt), город определяем локально по данным объявления. Итого ~6 запросов
   на прогон вместо 36 (3 сайта × 2 типа × 6 городов) — не забанят по частоте.
3. **Состояние целиком в Supabase.** `data/seen.db` и коммиты `chore: update seen listings`
   упраздняются — история репозитория перестаёт засоряться, гонки состояния исчезают.
4. **Идемпотентность апдейтов:** `last_update_id` хранится в БД, коммитится после обработки
   каждого апдейта; повторная обработка исключена и при отмене прогона на середине.
5. **Платёжный провайдер — абстракция.** Интерфейс `PaymentProvider` + ручное подтверждение
   (ManualProvider) с первого дня; реальный API (bepaid/Express-Pay) подключается в финальной
   фазе реализацией того же интерфейса, без переделки бота.

## Схема БД (Supabase / Postgres)

```sql
users        (id, chat_id UNIQUE, username, first_name, tariff 'free'|'premium',
              paid_until timestamptz NULL, dialog_state jsonb, is_admin bool,
              is_blocked bool, created_at)
filters      (id, user_id FK, property_type 'room'|'apartment', city_code text,
              max_price numeric NULL, enabled bool, created_at)
listings     (id text PK,  -- 'kufar:12345'
              source, property_type, city_code, title, url, photo_url,
              price_str, price_value, location, first_seen_at)
deliveries   (id, user_id FK, listing_id FK, created_at, sent_at NULL,
              UNIQUE(user_id, listing_id))   -- очередь отправки + дедуп на юзера
payments     (id, user_id FK, tariff, amount, currency, provider, order_id,
              status 'pending'|'confirmed'|'rejected', created_at, confirmed_at)
bot_state    (key text PK, value text)       -- last_update_id и пр.
users.last_batch_sent_at timestamptz         -- для батча free-юзеров
```

## Поток данных за один прогон scrape

1. Парсеры → все объявления по стране (комнаты + квартиры), с фото и городом.
2. `INSERT ... ON CONFLICT DO NOTHING` в `listings` → список реально новых.
3. Для каждого нового объявления — матчинг по активным фильтрам юзеров с активным
   тарифом → строки в `deliveries`.
4. Отправка: премиум — все pending сразу; free — только если `last_batch_sent_at`
   старше 30 мин (затем обновить). Карточка: фото (`sendPhoto` + caption, фолбэк
   на `sendMessage` без фото), заголовок, цена, город, ссылка, хэштеги.
5. Просроченные подписки: `tariff='premium' AND paid_until < now()` → перевести
   на free, уведомить («подписка закончилась, продлить — /premium»).

## Задачи

### Фаза 1 — Фундамент: Supabase и конфигурация

- [x] **T1. Схема Supabase + инструкция создания проекта**
  `deploy/supabase_schema.sql` — все таблицы/индексы из раздела «Схема БД» одним
  идемпотентным скриптом (IF NOT EXISTS). `docs/supabase-setup.md` — пошагово: создать
  проект, выполнить SQL в SQL Editor, взять URL + service_role key. Пользователь
  выполняет руками (5 минут), ключи кладёт в GitHub Secrets.
  Лог: н/п (SQL + доки). Блокирует: T2.

- [x] **T2. Слой доступа к данным `src/db.py` + расширение конфига**
  Класс `Database` поверх `supabase-py`: методы для users/filters/listings/deliveries/
  payments/bot_state (upsert_user, get_active_filters, insert_new_listings,
  queue_deliveries, pending_deliveries, confirm_payment, get/set state...).
  Абстрактный интерфейс + `FakeDatabase` (in-memory) для тестов. В `src/config.py`:
  `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ADMIN_CHAT_ID`, `TARIFF_PRICE_BYN` (=15),
  `FREE_BATCH_MINUTES` (=30), `PREMIUM_MAX_FILTERS` (=5). requirements.txt: +supabase.
  Лог: DEBUG — каждый запрос к БД (таблица, операция, число строк); WARN — ретраи/ошибки REST.
  Зависит: T1. Блокирует: T8, T9, T11.

### Фаза 2 — Парсинг: города, квартиры, фото

- [x] **T3. Справочник городов `src/cities.py`**
  Записи: code ('minsk', 'brest'...), название на русском, kufar_rgn, onliner_bounds
  (координатная рамка), realt-идентификаторы + функции `classify_kufar(ad)`,
  `classify_onliner(coords)`, `classify_realt(address)` → city_code | None.
  Коды регионов Kufar/Realt выяснить живыми запросами к API (проверить каждый город).
  Лог: DEBUG — результат классификации; WARN — объявление без распознанного города.
  Блокирует: T5, T6, T7.

- [x] **T4. Модель `Listing`: property_type, city_code, photo_url**
  Расширить dataclass + `to_telegram_html()`: тип и город в карточке, хэштеги
  (#минск #комната). Обновить существующие тесты.
  Лог: без изменений. Блокирует: T5, T6, T7.

- [x] **T5. Kufar: вся страна, комнаты + квартиры, фото**
  Переработать `kufar_rooms.py` → `kufar.py`: параметризованный класс, два инстанса
  (cat=1040 комнаты, cat=1010 квартиры), без rgn (вся Беларусь), size≈50, сортировка
  по свежести. Город — из ad_parameters (через cities.classify_kufar). Фото — из
  ad.images → URL yams.kufar.by. Проверить форматы живым запросом, обновить фикстуру.
  Лог: DEBUG — total/разобрано/без города; WARN — смена формата ответа.
  Зависит: T3, T4.

- [x] **T6. Onliner: вся страна, комнаты + квартиры, фото**
  `onliner.py`: rent_type room → комнаты; 1_room...4_rooms+ → квартиры. Рамка —
  вся Беларусь (или объединение рамок 6 городов, если API ограничивает выдачу —
  проверить живым запросом total). Город — по координатам (classify_onliner).
  Фото — поле photo. Фильтр по last_time_up сохранить. Обновить фикстуру.
  Лог: как в T5. Зависит: T3, T4.

- [x] **T7. Realt: вся страна, комнаты + квартиры, фото**
  `realt.py`: лента комнат + лента квартир (rent/flat-for-long), сортировка createdAt.
  Город — из адресных полей __NEXT_DATA__ (classify_realt). Фото — из objects[].images.
  Фильтр по возрасту сохранить. Обновить фикстуру.
  Лог: как в T5. Зависит: T3, T4.

### Фаза 3 — Бот: диалоги и тексты

- [x] **T8. Расширение Telegram-клиента `src/telegram.py`**
  Добавить: `get_updates(offset, timeout=0)`, `send_photo` (с caption HTML и фолбэком
  на sendMessage при ошибке фото), inline-клавиатуры (reply_markup), `answer_callback_query`,
  `edit_message_text`, обработка 429 (retry_after). Отправка в произвольный chat_id
  (не фиксированный).
  Лог: DEBUG — каждый вызов API и статус; WARN — 429 с длительностью паузы.
  Зависит: T2.

- [x] **T9. Роутер апдейтов `src/bot/router.py` + диалоговые состояния**
  Обработка message/callback_query. Состояние диалога — `users.dialog_state` (jsonb).
  Сценарии: `/start` (регистрация → приветствие → выбор тарифа); конструктор фильтра:
  тип (Комната/Квартира) → город (6 кнопок) → макс. цена (кнопки 300/500/800/1000/
  «не важно» BYN + ручной ввод числом); `/filters` — список с кнопками удалить/выключить;
  лимиты тарифа (free: 1 фильтр — при попытке второго предлагать премиум); `/premium`;
  `/help`; `/stop` (пауза рассылки). Идемпотентность: last_update_id в bot_state,
  обновление после каждого обработанного апдейта.
  Лог: INFO — каждая команда (chat_id, действие); DEBUG — переходы состояний;
  ERROR — необработанный апдейт (не роняет цикл).
  Зависит: T2, T8, T10.

- [x] **T10. Тексты бота `src/bot/texts.py`**
  Все сообщения в одном модуле: приветствие с описанием сервиса, инструкция после
  /start, витрина тарифов (таблица возможностей), подтверждение фильтра, «как оплатить»,
  «оплата получена», «подписка истекает через 3 дня», «подписка закончилась», /help.
  Оформление: HTML, эмодзи, короткие абзацы. Цены — подстановкой из конфига.
  Лог: н/п (константы). Блокирует: T9.

### Фаза 4 — Тарифы и доставка

- [x] **T11. Тарифы и матчинг `src/tariffs.py` + `src/matching.py`**
  `effective_tariff(user, now)` — premium при действующем paid_until, иначе free.
  Лимиты фильтров. `match_listing(listing, filters)` — тип + город + цена
  (None-цена объявления проходит любой фильтр цены — «договорная»).
  Даунгрейд просроченных подписок + уведомление. Напоминание за 3 дня до конца.
  Лог: DEBUG — счётчики матчинга (новых × фильтров → доставок); INFO — даунгрейды.
  Зависит: T2. Блокирует: T12.

- [x] **T12. Доставка `src/delivery.py`**
  Из `deliveries`: премиум — отправить всё pending; free — если last_batch_sent_at
  старше FREE_BATCH_MINUTES (после отправки обновить). Карточка с фото. Пауза между
  сообщениями (существующий rate-limit), пометка sent_at после успеха. Юзер заблокировал
  бота (403) → is_blocked=true, рассылку прекратить.
  Лог: INFO — итог (юзеров, сообщений, ошибок); WARN — 403/429.
  Зависит: T11.

### Фаза 5 — Платежи

- [x] **T13. Платёжный модуль `src/payments/`**
  `base.py` — интерфейс `PaymentProvider`: `create_invoice(user, tariff) → (instructions,
  order_id)`, `check_status(order_id)`. `manual.py` — ManualProvider: инструкция с
  реквизитами из конфига (`PAYMENT_DETAILS`), кнопка «Я оплатил ✅» → payment(pending) →
  уведомление админу с кнопками «Подтвердить/Отклонить» → confirm → paid_until += 30 дней.
  `bepaid.py` — каркас под HTTP API (create + status), помечен NotImplemented до финальной
  фазы. Админ-команды в роутере: `/approve <id>`, `/grant <chat_id> <days>`, `/stats`
  (юзеры/подписки/доставки за сутки). Только для ADMIN_CHAT_ID.
  Лог: INFO — каждый платёж и смена статуса (id, user, сумма); WARN — попытка
  админ-команды не-админом.
  Зависит: T9, T11.

### Фаза 6 — Оркестрация и деплой

- [ ] **T14. Точки входа `src/jobs/updates.py` и `src/jobs/scrape.py`**
  `updates.py`: цикл getUpdates → router (лёгкий, без импорта парсеров/bs4).
  `scrape.py`: парсеры → новые listings → матчинг → deliveries → доставка →
  обслуживание подписок. Перенос дедупликации с seen.db на таблицу listings;
  `src/storage.py` и `data/seen.db` удалить. `src/main.py` — переключить на новый
  сценарий (обратная совместимость одиночного запуска для локальной отладки).
  Лог: INFO — сводка прогона (найдено/новых/доставок/отправлено/ошибок).
  Зависит: T5, T6, T7, T9, T12.

- [ ] **T15. Workflows + cron-job.org**
  `.github/workflows/bot.yml`: workflow_dispatch (+schedule fallback */5), только
  httpx+supabase c pip-кэшем, `python -m src.jobs.updates`, concurrency `bot` /
  cancel-in-progress: true, timeout 5 мин. `scrape.yml` переписать: `python -m
  src.jobs.scrape`, убрать шаг коммита seen.db, concurrency `scrape`. Секреты:
  SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_CHAT_ID, PAYMENT_DETAILS (+существующий
  TELEGRAM_BOT_TOKEN; TELEGRAM_CHAT_ID больше не нужен). `docs/deploy.md`: настройка
  двух заданий на cron-job.org (bot — каждую минуту, scrape — каждые 2–3 мин),
  где взять токены, как проверить.
  Лог: шаги CI выводят сводки прогонов. Зависит: T14.

### Фаза 7 — Тесты и оформление

- [ ] **T16. Тесты новой функциональности**
  На FakeDatabase: тарифы (лимиты, даунгрейд, батч free), матчинг (тип/город/цена/
  договорная), роутер (симулированные апдейты: /start → тариф → фильтр → подтверждение;
  идемпотентность по update_id; лимит фильтров free), платежи (pending → confirm →
  paid_until; отклонение), парсеры квартир и классификация городов на обновлённых
  фикстурах, delivery (403 → is_blocked). Все существующие тесты проходят.
  Зависит: T14 (фактически — по мере готовности модулей).

- [ ] **T17. Оформление и подготовка к запуску**
  BotFather: описание бота, about, список команд (setcommands), аватар — инструкция
  в `docs/bot-setup.md` с готовыми текстами. README переписать: что за сервис,
  архитектура (схема), полный чек-лист запуска (Supabase → Secrets → cron-job.org →
  BotFather). Онбординг-сообщение в боте с примером карточки объявления.
  Зависит: T15, T16.

### Финальная фаза (отдельно, в процессе тестирования — вне этого плана)

- Подключение реального платёжного API (bepaid/Express-Pay) реализацией
  `PaymentProvider` — потребует договор с платёжкой. До этого работает ManualProvider.

## План коммитов (17 задач — чекпойнты)

- **Коммит 1** (T1–T2): `feat: supabase schema and database layer`
- **Коммит 2** (T3–T7): `feat: apartments + all regional cities parsers with photos`
- **Коммит 3** (T8–T10): `feat: interactive bot (menu, filters, tariffs dialog)`
- **Коммит 4** (T11–T12): `feat: tariff logic and per-user delivery`
- **Коммит 5** (T13): `feat: payments module with manual confirmation`
- **Коммит 6** (T14–T15): `feat: jobs entrypoints and CI workflows, drop seen.db`
- **Коммит 7** (T16–T17): `test+docs: coverage for bot/tariffs/parsers, launch guide`

## Риски и открытые вопросы

1. **Коды регионов Kufar/Realt и рамки Onliner** — выяснить живыми запросами в T3;
   если API Onliner ограничивает выдачу по большой рамке, перейти на запрос по рамке
   каждого города (6 запросов вместо 1 — приемлемо).
2. **Latency ответов бота ~40–90 сек** — принятый компромисс бесплатной инфраструктуры;
   в текстах бота ожидание проговаривается («обрабатываю, отвечу в течение минуты»).
   Апгрейд-путь: webhook на PythonAnywhere или VPS — интерфейс router от этого не меняется.
3. **Лимиты GitHub Actions** — два workflow ×~1 мин выполнения: суммарно ~2000+ мин/день,
   допустимо только для публичного репозитория. Данные юзеров при этом в Supabase, в репо
   не попадают. Интенсивное использование Actions под ботом — серая зона ToS GitHub:
   если прилетит ограничение, тот же код переезжает на VPS/Oracle Free без переделки.
4. **Telegram 429 при росте базы** — до сотен юзеров хватает паузы 0.5 с; дальше —
   батчить по 25–30 сообщений/сек.
5. **Supabase free** — 500 МБ БД: с очисткой старых listings/deliveries (> 30 дней,
   отдельный шаг в scrape) хватит надолго.
