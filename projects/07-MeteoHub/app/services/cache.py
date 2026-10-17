"""
Кэш поверх PostgreSQL для ответов внешних источников MeteoHub.

Таблицы:
  - geocode_cache  — запрос → координаты + метаданные;
  - weather_cache  — (координаты, вид, хэш параметров) → JSON ответа.

Виды (kind):
  - "met_forecast" — сырой GeoJSON MET Norway;
  - "om_history"   — JSON Open-Meteo Archive.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from timezonefinder import TimezoneFinder

from db.connection import get_pool, get_settings
from app.services.nominatim import geocode

# Инициализируем один раз при старте (работает быстро после первого вызова).
_tf = TimezoneFinder()
from app.services.met_norway import get_forecast as met_get_forecast
from app.services.open_meteo_archive import get_history as om_get_history
from app.services import aggregator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _params_hash(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Геокодинг
# --------------------------------------------------------------------------
def get_or_fetch_geocode(query: str) -> dict | None:
    """Найти город через кэш → Nominatim. None если не найден.

    Возвращает нормализованный dict одинаковой формы при кэш-хите и промахе:
        {"latitude": float, "longitude": float, "display_name": str,
         "country_code": str|None, "timezone": str|None, "raw": dict}
    """
    settings = get_settings()
    pool = get_pool()

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select latitude, longitude, display_name,
                       country_code, timezone, raw
                from geocode_cache
                where query = %s and expires_at > now()
                """,
                (query,),
            )
            row = cur.fetchone()
            if row is not None:
                return {
                    "latitude": float(row[0]),
                    "longitude": float(row[1]),
                    "display_name": row[2],
                    "country_code": row[3],
                    "timezone": row[4],
                    "raw": row[5],
                }

    result = geocode(query)
    if result is None:
        return None

    # Определяем часовой пояс по координатам
    tz_name = _tf.timezone_at(lat=result["latitude"], lng=result["longitude"])
    if tz_name is None:
        tz_name = "UTC"

    expires_at = _now() + timedelta(seconds=settings.cache_ttl_geocode)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into geocode_cache
                    (query, latitude, longitude, display_name,
                     country_code, timezone, raw, expires_at)
                values
                    (%(query)s, %(lat)s, %(lon)s, %(display_name)s,
                     %(country_code)s, %(timezone)s, %(raw)s, %(expires_at)s)
                on conflict (query) do update set
                    latitude     = excluded.latitude,
                    longitude    = excluded.longitude,
                    display_name = excluded.display_name,
                    country_code = excluded.country_code,
                    timezone     = excluded.timezone,
                    raw          = excluded.raw,
                    created_at   = now(),
                    expires_at   = excluded.expires_at
                """,
                {
                    "query": query,
                    "lat": result["latitude"],
                    "lon": result["longitude"],
                    "display_name": result["display_name"],
                    "country_code": result["country_code"],
                    # Nominatim не отдаёт TZ; пишем UTC-заглушку (см. aggregator).
                    "timezone": tz_name,
                    "raw": json.dumps(result["raw"], ensure_ascii=False),
                    "expires_at": expires_at,
                },
            )
        conn.commit()

    result["timezone"] = tz_name
    return result


# --------------------------------------------------------------------------
# Прогноз (MET Norway)
# --------------------------------------------------------------------------
def get_or_fetch_met_forecast(lat: float, lon: float) -> dict:
    """
    Сырой GeoJSON MET Norway с кэшем.
    Побочный эффект: при первом получении рассчитывает дневные агрегаты
    и upsert-ит их в weather_daily.
    """
    settings = get_settings()
    pool = get_pool()
    phash = _params_hash({})

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select payload from weather_cache
                where latitude = %s::numeric(9, 6)
                  and longitude = %s::numeric(9, 6)
                  and kind = 'met_forecast' and params_hash = %s
                  and expires_at > now()
                """,
                (lat, lon, phash),
            )
            row = cur.fetchone()
            if row is not None:
                return row[0]

    payload = met_get_forecast(lat, lon)
    expires_at = _now() + timedelta(seconds=settings.cache_ttl_weather)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into weather_cache
                    (latitude, longitude, kind, params_hash, payload, expires_at)
                values
                    (%(lat)s, %(lon)s, 'met_forecast', %(phash)s,
                     %(payload)s, %(expires_at)s)
                on conflict (latitude, longitude, kind, params_hash) do update set
                    payload    = excluded.payload,
                    created_at = now(),
                    expires_at = excluded.expires_at
                """,
                {
                    "lat": lat,
                    "lon": lon,
                    "phash": phash,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "expires_at": expires_at,
                },
            )
        conn.commit()

    # Побочный эффект: сбрасываем дневные агрегаты в weather_daily.
    try:
        daily = aggregator.extract_daily(payload, days=7)
        aggregator.persist_daily(lat, lon, daily)
    except Exception:
        # Ошибка агрегатора не должна ломать основной сценарий кэширования.
        pass

    return payload


# --------------------------------------------------------------------------
# История (Open-Meteo Archive)
# --------------------------------------------------------------------------
def get_or_fetch_history(
    lat: float, lon: float, start_date: str, end_date: str
) -> dict:
    """Исторические данные Open-Meteo с кэшем."""
    settings = get_settings()
    pool = get_pool()
    params = {"start_date": start_date, "end_date": end_date}
    phash = _params_hash(params)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select payload from weather_cache
                where latitude = %s::numeric(9, 6)
                  and longitude = %s::numeric(9, 6)
                  and kind = 'om_history' and params_hash = %s
                  and expires_at > now()
                """,
                (lat, lon, phash),
            )
            row = cur.fetchone()
            if row is not None:
                return row[0]

    payload = om_get_history(lat, lon, start_date, end_date)
    expires_at = _now() + timedelta(seconds=settings.cache_ttl_weather)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into weather_cache
                    (latitude, longitude, kind, params_hash, payload, expires_at)
                values
                    (%(lat)s, %(lon)s, 'om_history', %(phash)s,
                     %(payload)s, %(expires_at)s)
                on conflict (latitude, longitude, kind, params_hash) do update set
                    payload    = excluded.payload,
                    created_at = now(),
                    expires_at = excluded.expires_at
                """,
                {
                    "lat": lat,
                    "lon": lon,
                    "phash": phash,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "expires_at": expires_at,
                },
            )
        conn.commit()

    return payload