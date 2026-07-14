-- ============================================================================
-- Схема БД для Telegram-бота аренды (Supabase / Postgres).
--
-- Скрипт идемпотентен: можно выполнять повторно, существующие таблицы не
-- пострадают. Выполнять в Supabase: Dashboard -> SQL Editor -> New query ->
-- вставить целиком -> Run. Подробная инструкция: docs/supabase-setup.md
-- ============================================================================

-- ----------------------------------------------------------------------------
-- users — зарегистрированные пользователи бота.
-- dialog_state — состояние диалога (конструктор фильтра и т.п.), jsonb.
-- last_batch_sent_at — время последней батч-рассылки для free-тарифа.
-- ----------------------------------------------------------------------------
create table if not exists users (
    id                 bigserial primary key,
    chat_id            bigint      not null unique,
    username           text,
    first_name         text,
    tariff             text        not null default 'free'
                       check (tariff in ('free', 'premium')),
    paid_until         timestamptz,
    dialog_state       jsonb       not null default '{}'::jsonb,
    is_admin           boolean     not null default false,
    is_blocked         boolean     not null default false,
    paused             boolean     not null default false,
    last_batch_sent_at timestamptz,
    created_at         timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- filters — поисковые фильтры пользователей (комната/квартира, город, цена).
-- max_price NULL = «цена не важна».
-- ----------------------------------------------------------------------------
create table if not exists filters (
    id            bigserial primary key,
    user_id       bigint      not null references users (id) on delete cascade,
    property_type text        not null
                  check (property_type in ('room', 'apartment')),
    city_code     text        not null,
    max_price     numeric,
    enabled       boolean     not null default true,
    created_at    timestamptz not null default now()
);

create index if not exists idx_filters_user_id on filters (user_id);
create index if not exists idx_filters_enabled on filters (city_code, property_type)
    where enabled;

-- ----------------------------------------------------------------------------
-- listings — все увиденные объявления (замена локального seen.db).
-- id — глобальный ключ вида 'kufar:12345' / 'onliner:98765' / 'realt:...'.
-- city_code NULL = город не распознан (такие никому не рассылаются).
-- ----------------------------------------------------------------------------
create table if not exists listings (
    id            text        primary key,
    source        text        not null,
    property_type text        not null
                  check (property_type in ('room', 'apartment')),
    city_code     text,
    title         text        not null,
    url           text        not null,
    photo_url     text,
    price_str     text,
    price_value   numeric,
    location      text,
    first_seen_at timestamptz not null default now()
);

create index if not exists idx_listings_first_seen_at on listings (first_seen_at);

-- ----------------------------------------------------------------------------
-- deliveries — очередь доставки: какое объявление какому юзеру отправить.
-- sent_at NULL = ещё не отправлено (pending). UNIQUE защищает от дублей.
-- ----------------------------------------------------------------------------
create table if not exists deliveries (
    id         bigserial primary key,
    user_id    bigint      not null references users (id) on delete cascade,
    listing_id text        not null references listings (id) on delete cascade,
    created_at timestamptz not null default now(),
    sent_at    timestamptz,
    unique (user_id, listing_id)
);

create index if not exists idx_deliveries_pending on deliveries (user_id)
    where sent_at is null;

-- ----------------------------------------------------------------------------
-- payments — платежи за подписку.
-- provider: 'manual' (ручное подтверждение) | 'bepaid' | ... .
-- order_id — идентификатор счёта у провайдера (для manual — сгенерированный).
-- ----------------------------------------------------------------------------
create table if not exists payments (
    id           bigserial primary key,
    user_id      bigint      not null references users (id) on delete cascade,
    tariff       text        not null default 'premium',
    amount       numeric     not null,
    currency     text        not null default 'BYN',
    provider     text        not null,
    order_id     text        unique,
    status       text        not null default 'pending'
                 check (status in ('pending', 'confirmed', 'rejected')),
    created_at   timestamptz not null default now(),
    confirmed_at timestamptz
);

create index if not exists idx_payments_status on payments (status);
create index if not exists idx_payments_user_id on payments (user_id);

-- ----------------------------------------------------------------------------
-- bot_state — служебное состояние бота (key/value).
-- Ключи: 'last_update_id' — offset обработанных апдейтов Telegram.
-- ----------------------------------------------------------------------------
create table if not exists bot_state (
    key   text primary key,
    value text not null
);

-- ----------------------------------------------------------------------------
-- Row Level Security: включаем на всех таблицах БЕЗ политик.
-- Бот ходит через service_role key (обходит RLS), а публичный anon key
-- при этом не может прочитать ни строки — данные юзеров защищены.
-- ----------------------------------------------------------------------------
alter table users      enable row level security;
alter table filters    enable row level security;
alter table listings   enable row level security;
alter table deliveries enable row level security;
alter table payments   enable row level security;
alter table bot_state  enable row level security;
