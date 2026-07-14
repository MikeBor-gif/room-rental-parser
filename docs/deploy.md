# Деплой: GitHub Actions + cron-job.org

Бот работает на двух workflow GitHub Actions, которые снаружи дёргает
cron-job.org (штатное расписание GitHub задерживается на 10–30+ минут,
cron-job.org срабатывает точно):

| Workflow | Что делает | Как часто дёргать |
|---|---|---|
| `bot.yml` | отвечает на команды и кнопки | каждую **1 минуту** |
| `scrape.yml` | парсит сайты и рассылает объявления | каждые **2–3 минуты** |

## Шаг 1. Секреты репозитория

**Settings → Secrets and variables → Actions → Secrets**:

| Secret | Что это |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather (уже задан) |
| `SUPABASE_URL` | Project URL из Supabase (см. docs/supabase-setup.md) |
| `SUPABASE_SERVICE_KEY` | service_role key из Supabase |
| `ADMIN_CHAT_ID` | ваш chat_id — сюда приходят заявки на оплату, доступны /approve, /grant, /stats |
| `PAYMENT_DETAILS` | реквизиты для оплаты, например: `Перевод на карту 1234 5678 9012 3456 (Иван И.)` |

**Variables** (необязательно, есть значения по умолчанию):

| Variable | По умолчанию | Что это |
|---|---|---|
| `TARIFF_PRICE_BYN` | 15 | цена премиума, BYN/30 дней |
| `FREE_BATCH_MINUTES` | 30 | период подборок на бесплатном тарифе |
| `PREMIUM_MAX_FILTERS` | 5 | лимит фильтров на премиуме |

Старый секрет `TELEGRAM_CHAT_ID` больше не используется (можно удалить).

## Шаг 2. Персональный токен GitHub (для cron-job.org)

cron-job.org дёргает GitHub API — нужен токен с правом запускать workflow:

1. GitHub → Settings (профиля) → Developer settings →
   **Fine-grained personal access tokens** → Generate new token.
2. Repository access: **Only select repositories** → этот репозиторий.
3. Permissions → Repository permissions → **Actions: Read and write**.
4. Скопировать токен (`github_pat_...`).

## Шаг 3. Два задания на cron-job.org

На [console.cron-job.org](https://console.cron-job.org) создать **два** cronjob
(второй — копия первого с другим URL и расписанием):

**Задание 1 — bot (каждую минуту):**

- **URL:** `https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/bot.yml/dispatches`
- **Schedule:** every 1 minute
- **Request method:** POST
- **Headers** (вкладка Advanced):
  - `Authorization`: `Bearer github_pat_...` (токен из шага 2)
  - `Accept`: `application/vnd.github+json`
  - `Content-Type`: `application/json`
- **Request body:** `{"ref":"main"}`

**Задание 2 — scrape (каждые 2 минуты):**

- То же самое, но URL: `.../actions/workflows/scrape.yml/dispatches`
  и Schedule: every 2 minutes.

Успешный запуск возвращает **204 No Content** — в истории cron-job.org
это зелёный статус.

## Шаг 4. Проверка

1. Вкладка **Actions** в репозитории: workflow `bot` и `scrape` появляются
   каждые 1–3 минуты и завершаются зелёными.
2. Написать боту `/start` — ответ должен прийти в течение ~1–2 минут.
3. Настроить фильтр и дождаться первого объявления (для нового фильтра
   придут только объявления, появившиеся ПОСЛЕ его создания).
4. В Supabase → Table Editor видно пользователей, фильтры и доставки.

## Частые проблемы

- **404 от api.github.com** — проверьте OWNER/REPO в URL и что токен выдан
  на этот репозиторий.
- **403 Resource not accessible** — у токена нет права Actions: Read and write.
- **Workflow не стартует, cron-job зелёный** — проверьте, что в body указана
  существующая ветка: `{"ref":"main"}`.
- **Бот молчит** — откройте лог последнего прогона `bot` во вкладке Actions:
  ошибки конфигурации (не задан секрет) видны в первой строке лога.
