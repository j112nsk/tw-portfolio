-- ============================================================================
-- MeteoHub — схема БД (версия 1.0)
-- Назначение: таблицы для кэша геокодинга, кэша погодных запросов
--             и дневных агрегатов.
-- Правила: DM-01 (snake_case, множественное число), DM-02 (UTC для меток),
--          DM-03 (id — bigserial), PM-03 (ссылки по коду, а не по id).
-- ============================================================================

-- Кэш геокодинга: населённый пункт → координаты.
-- TTL задаётся приложением (переменная CACHE_TTL_GEOCODE).
create table if not exists geocode_cache (
    id           bigserial      primary key,
    query        text           not null,          -- как ввёл пользователь (нормализовано)
    latitude     numeric(9, 6)  not null,
    longitude    numeric(9, 6)  not null,
    display_name text           not null,          -- «Москва, Россия»
    country_code varchar(2),                        -- ISO 3166-1 alpha-2
    timezone     text           not null,          -- IANA, напр. Europe/Moscow
    raw          jsonb          not null,          -- сырой ответ Open-Meteo Geocoding
    created_at   timestamptz    not null default now(),
    expires_at   timestamptz    not null
);

create unique index if not exists ux_geocode_cache_query
    on geocode_cache (query);

create index if not exists ix_geocode_cache_expires
    on geocode_cache (expires_at);

comment on table geocode_cache is
    'Кэш результатов Open-Meteo Geocoding API. Запись считается актуальной, '
    'пока now() < expires_at. TTL — из CACHE_TTL_GEOCODE.';


-- Кэш погодных запросов: (координаты, вид, диапазон) → JSON ответа.
-- Вид: current | forecast | history.
create table if not exists weather_cache (
    id           bigserial      primary key,
    latitude     numeric(9, 6)  not null,
    longitude    numeric(9, 6)  not null,
    kind         varchar(16)    not null,          -- current | forecast | history
    params_hash  text           not null,          -- хэш набора параметров запроса
    payload      jsonb          not null,          -- нормализованный ответ
    created_at   timestamptz    not null default now(),
    expires_at   timestamptz    not null
);

create unique index if not exists ux_weather_cache_key
    on weather_cache (latitude, longitude, kind, params_hash);

create index if not exists ix_weather_cache_expires
    on weather_cache (expires_at);

comment on table weather_cache is
    'Кэш ответов Open-Meteo Forecast/Archive API. Уникальность — по '
    '(координаты, вид данных, хэш параметров). TTL — из CACHE_TTL_WEATHER.';


-- Дневные агрегаты для аналитики: тёплый/холодный/дождливый/ветреный день.
-- Сохраняются один раз на (координаты, дата) и используются для отчётов.
create table if not exists weather_daily (
    id                     bigserial      primary key,
    latitude               numeric(9, 6)  not null,
    longitude              numeric(9, 6)  not null,
    date                   date           not null,
    temperature_max        numeric(5, 2),
    temperature_min        numeric(5, 2),
    temperature_mean       numeric(5, 2),
    apparent_temperature_max numeric(5, 2),
    precipitation_sum      numeric(6, 2),
    precipitation_hours    numeric(4, 1),
    wind_speed_max         numeric(5, 2),
    wind_gusts_max         numeric(5, 2),
    wind_direction_dominant numeric(5, 1),
    weather_code           integer,
    raw                    jsonb          not null,  -- сырой daily-блок Open-Meteo
    created_at             timestamptz    not null default now(),
    updated_at             timestamptz    not null default now()
);

create unique index if not exists ux_weather_daily_key
    on weather_daily (latitude, longitude, date);

create index if not exists ix_weather_daily_date
    on weather_daily (date desc);

comment on table weather_daily is
    'Дневные агрегаты погоды для аналитики (самый тёплый/холодный день, '
    'макс. осадки, сильный ветер). Заполняется из daily-блока Open-Meteo.';


-- Триггер обновления updated_at.
create or replace function trg_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists tg_weather_daily_updated_at on weather_daily;
create trigger tg_weather_daily_updated_at
    before update on weather_daily
    for each row
    execute function trg_set_updated_at();