"""
Аналитические агрегаты по таблице weather_daily.

Таблица заполняется автоматически при первом запросе прогноза
(get_or_fetch_met_forecast → aggregator.extract_daily → persist_daily).
Поэтому эндпоинт /analytics сначала вызывает /forecast-логику, затем
выполняет SQL-запросы.

Каждый запрос — отдельный SQL, простой и наглядный. Все параметры —
именованные; координаты приводятся к numeric(9, 6) для совпадения
с типом колонок.
"""
from __future__ import annotations

from datetime import date, timedelta

from db.connection import get_pool


def _query(cur, sql: str, params: dict):
    cur.execute(sql, params)
    return cur.fetchone()


def get_analytics(lat: float, lon: float, days: int = 7) -> dict | None:
    """
    Вернуть агрегаты за окно [today_utc, today_utc + days - 1].

    None — если в weather_daily нет данных за это окно
    (значит, агрегатор не отработал или прогноз не запрашивался).
    """
    today = date.today()
    end = today + timedelta(days=days - 1)
    base = {
        "lat": lat,
        "lon": lon,
        "start": today,
        "end": end,
    }

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Проверяем, что данные вообще есть.
            row = _query(
                cur,
                """
                select count(*)
                from weather_daily
                where latitude = %(lat)s::numeric(9, 6)
                  and longitude = %(lon)s::numeric(9, 6)
                  and date between %(start)s and %(end)s
                """,
                base,
            )
            if not row or row[0] == 0:
                return None

            # Самый тёплый — по максимальной дневной температуре.
            warmest = _query(
                cur,
                """
                select date, temperature_max, weather_code
                from weather_daily
                where latitude = %(lat)s::numeric(9, 6)
                  and longitude = %(lon)s::numeric(9, 6)
                  and date between %(start)s and %(end)s
                  and temperature_max is not null
                order by temperature_max desc, date asc
                limit 1
                """,
                base,
            )

            # Самый холодный — по минимальной дневной температуре.
            coldest = _query(
                cur,
                """
                select date, temperature_min, weather_code
                from weather_daily
                where latitude = %(lat)s::numeric(9, 6)
                  and longitude = %(lon)s::numeric(9, 6)
                  and date between %(start)s and %(end)s
                  and temperature_min is not null
                order by temperature_min asc, date asc
                limit 1
                """,
                base,
            )

            # Самый дождливый — по сумме осадков за день.
            wettest = _query(
                cur,
                """
                select date, precipitation_sum, weather_code
                from weather_daily
                where latitude = %(lat)s::numeric(9, 6)
                  and longitude = %(lon)s::numeric(9, 6)
                  and date between %(start)s and %(end)s
                  and precipitation_sum is not null
                order by precipitation_sum desc, date asc
                limit 1
                """,
                base,
            )

            # Самый ветреный — по максимальной скорости ветра.
            windiest = _query(
                cur,
                """
                select date, wind_speed_max, weather_code
                from weather_daily
                where latitude = %(lat)s::numeric(9, 6)
                  and longitude = %(lon)s::numeric(9, 6)
                  and date between %(start)s and %(end)s
                  and wind_speed_max is not null
                order by wind_speed_max desc, date asc
                limit 1
                """,
                base,
            )

    def _pack(row, unit: str) -> dict | None:
        if row is None:
            return None
        return {
            "date": row[0],
            "value": float(row[1]),
            "unit": unit,
            "weather_code": row[2],
        }

    return {
        "period_days": days,
        "warmest": _pack(warmest, "°C"),
        "coldest": _pack(coldest, "°C"),
        "wettest": _pack(wettest, "мм"),
        "windiest": _pack(windiest, "м/с"),
    }