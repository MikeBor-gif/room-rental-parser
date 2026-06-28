# План: Парсер «Комнаты в аренду, Минск» с Kufar (JSON API)

**Дата создания:** 2026-06-28
**Режим:** fast
**Тип:** feature (первый реальный парсер)

## Настройки

- **Тесты:** да (парсинг JSON-ответа на сохранённой фикстуре)
- **Логирование:** подробное (DEBUG)

## Контекст разведки (проверено вживую)

- Прямой GET HTML страницы `re.kufar.by/...` → **403 Forbidden** (сайт блокирует не-браузер).
- Публичный JSON-API работает (200): `https://api.kufar.by/search-api/v2/search/rendered`
- Параметры для «комнаты в аренду, Минск»:
  - `cat=1040` (Комнаты), `typ=let` (аренда), `rgn=7` (Минск), `lang=ru`, `size=<N>`, `cur=BYN`
- Структура ответа: `{ ads: [...], total, page_type }`. Поля объявления:
  `ad_id`, `list_id`, `ad_link` (`https://re.kufar.by/vi/<id>`), `subject`,
  `price_byn`/`price_usd` (в копейках — делить на 100), `list_time` (ISO, UTC),
  `body_short`, `images`, `ad_parameters` (Регион/Город/Площадь и т.д.).

## Задачи

- ✅ **K1. Реализовать `KufarRoomsParser`** — `src/parsers/kufar_rooms.py`
  Наследник `BaseParser`. `fetch()` запрашивает API (cat=1040, typ=let, rgn=7),
  метод `parse(json_dict) -> list[Listing]` разбирает `ads[]` в `Listing`:
  - `id = f"kufar:{ad_id}"` (стабильный)
  - `title = subject`, `url = ad_link`
  - `price = f"{price_byn/100:.0f} BYN"`, `price_value = price_byn/100`
  - `location` — из `ad_parameters` (Город / Район)
  Заголовки запроса — браузерные (User-Agent, Accept, Accept-Language).
  Лог: DEBUG — URL, total, количество разобранных; WARN — пропуск битого объявления.

- ✅ **K2. Подключить парсер в оркестратор** — `src/main.py`
  В `PARSER_CLASSES` заменить заглушку `ExampleSiteParser` на `KufarRoomsParser`
  (файл `example_site.py` оставить как шаблон). Лог: INFO — какой парсер активен.

- ✅ **K3. Тест на JSON-фикстуре** — `tests/fixtures/kufar_rooms.json`, `tests/test_kufar_parser.py`
  Сохранить небольшой реальный ответ API как фикстуру; проверить, что `parse()`
  извлекает ожидаемые поля и корректно считает цену (копейки → BYN).

## Открытые вопросы (не блокируют)

- Фильтры (макс. цена / ключевые слова) уже поддержаны в оркестраторе через
  переменные `MAX_PRICE` / `KEYWORDS` — при желании зададите в GitHub Variables.
- Частота — текущая (cron каждые ~15 мин).
