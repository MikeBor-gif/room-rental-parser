# Парсер объявлений об аренде комнат → Telegram

Сервис периодически обходит сайты с объявлениями об аренде комнат, находит **новые**
и присылает их в Telegram. Запускается по расписанию через **GitHub Actions** —
постоянно работающий сервер не нужен и всё бесплатно.

## Как это работает

```
Каждые ~15 минут (GitHub Actions по cron):
  1. Парсеры заходят на сайты и собирают объявления
  2. Сравнение с базой «уже виденных» (data/seen.db)
  3. Новые объявления → отправляются вам в Telegram
  4. Обновлённая база коммитится обратно в репозиторий
```

## Структура проекта

```
parser/
├── .github/workflows/scrape.yml   # запуск по расписанию + коммит состояния
├── src/
│   ├── main.py            # оркестратор: парсеры → дедуп → Telegram
│   ├── config.py          # конфиг из переменных окружения / .env
│   ├── logging_setup.py   # настройка логирования (LOG_LEVEL)
│   ├── models.py          # модель Listing
│   ├── http_client.py     # httpx с ретраями
│   ├── storage.py         # SQLite-хранилище виденных объявлений
│   ├── telegram.py        # отправка в Telegram Bot API
│   └── parsers/
│       ├── base.py        # интерфейс BaseParser
│       └── example_site.py# парсер-шаблон (замените на реальный сайт)
├── tests/                 # pytest: storage, дедуп, парсер на фикстуре
├── data/seen.db           # состояние (создаётся автоматически)
├── requirements.txt
└── .env.example
```

## Быстрый старт (локально)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env       # заполните токен и chat_id
python -m src.main
```

Тесты:

```bash
pytest
```

## Настройка Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather) → команда `/newbot` → задайте имя.
   BotFather выдаст **токен** вида `123456789:AAExxxxxxxxxxxxxxxxxxxxxxx`.
2. Узнайте свой **chat_id**: напишите боту [@userinfobot](https://t.me/userinfobot)
   — он пришлёт ваш числовой `id`.
   (Альтернатива: напишите своему боту любое сообщение и откройте
   `https://api.telegram.org/bot<ТОКЕН>/getUpdates` — там будет `chat.id`.)
3. Впишите оба значения в `.env` (локально) или в Secrets репозитория (для деплоя).

## Деплой через GitHub Actions (бесплатно, 24/7 по расписанию)

1. Создайте репозиторий на GitHub (приватный) и запушьте туда проект:
   ```bash
   git init
   git add .
   git commit -m "init: room rental parser"
   git branch -M main
   git remote add origin https://github.com/<USER>/<REPO>.git
   git push -u origin main
   ```
2. В репозитории: **Settings → Secrets and variables → Actions → New repository secret**
   и добавьте:
   - `TELEGRAM_BOT_TOKEN` — токен от BotFather
   - `TELEGRAM_CHAT_ID` — ваш chat_id
3. (Необязательно) Там же во вкладке **Variables** можно задать фильтры:
   - `MAX_PRICE` — максимальная цена (число)
   - `KEYWORDS` — ключевые слова через запятую
4. Готово. Workflow `scrape.yml` сам запустится по расписанию. Можно запустить
   вручную: вкладка **Actions → scrape → Run workflow**.

### Изменить частоту проверки

В `.github/workflows/scrape.yml` поменяйте строку `cron`:

```yaml
- cron: "*/15 * * * *"   # каждые 15 минут
- cron: "*/30 * * * *"   # каждые 30 минут
- cron: "0 * * * *"      # раз в час
```

> ⚠️ GitHub Actions запускает расписание с задержкой ~5–15 минут и может пропускать
> запуски при высокой нагрузке. Для мониторинга объявлений этого достаточно.

## Как добавить парсер под новый сайт

1. Скопируйте `src/parsers/example_site.py` → `src/parsers/<имя_сайта>.py`.
2. Поменяйте `name`, `BASE_URL`, `LIST_URL` и CSS-селекторы в методе `parse()`
   под разметку конкретного сайта. У каждого `Listing` должен быть **стабильный `id`**
   (лучше всего — id объявления с сайта; иначе используйте `self.make_id(...)` по URL).
3. Зарегистрируйте класс в `src/main.py` в списке `PARSER_CLASSES`.
4. Добавьте тест на HTML-фикстуре по образцу `tests/test_example_parser.py`.

> Пришлите ссылки на нужные сайты — и парсеры под них добавим по этой схеме.

## Переменные окружения

| Переменная           | Обязательна | Описание                                  |
|----------------------|-------------|-------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | да          | Токен бота от @BotFather                   |
| `TELEGRAM_CHAT_ID`   | да          | Чат, куда слать уведомления                |
| `LOG_LEVEL`          | нет         | `DEBUG`/`INFO`/`WARNING`/`ERROR` (умолч. `INFO`) |
| `MAX_PRICE`          | нет         | Фильтр: макс. цена                         |
| `KEYWORDS`           | нет         | Фильтр: ключевые слова через запятую       |
