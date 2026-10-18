"""
Преобразование сырого GeoJSON MET Norway в нормализованные структуры:
  - extract_current(met)         — «текущая погода» из первой точки timeseries;
  - extract_daily(met, days)     — список дневных агрегатов (список dict);
  - persist_daily(lat, lon, recs) — upsert в weather_daily.

Правила:
  - Все времена в ответе MET Norway — UTC.
  - Дневные агрегаты группируются по UTC-дате. Это осознанное упрощение MVP;
    при необходимости локальных дат добавим tz-параметр в следующей итерации.
  - Осадки: для каждой точки берём next_1_hours если есть, иначе next_6_hours
    (это покрывает и переходную зону, когда MET Norway меняет шаг с 1 ч на 6 ч).
  - Доминирующее направление ветра = направление в час максимальной скорости.
  - weather_code: маппинг symbol_code → WMO. Неизвестный символ → None.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from db.connection import get_pool


SYMBOL_TO_WMO = {
    "clearsky_day": 0, "clearsky_night": 0,
    "fair_day": 1, "fair_night": 1,
    "partlycloudy_day": 2, "partlycloudy_night": 2,
    "cloudy": 3,
    "fog": 45,
    "lightrain": 61, "lightrainshowers_day": 80, "lightrainshowers_night": 80,
    "rain": 63, "rainshowers_day": 80, "rainshowers_night": 80,
    "heavyrain": 65, "heavyrainshowers_day": 82, "heavyrainshowers_night": 82,
    "lightsleet": 66, "sleet": 67,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers_day": 85, "lightsnowshowers_night": 85,
    "snowshowers_day": 85, "snowshowers_night": 85,
    "rainandthunder": 95, "heavyrainandthunder": 95,
    "sleetandthunder": 96, "snowandthunder": 95,
}


def _parse_time(iso: str) -> datetime:
    """ISO8601 c Z → aware UTC datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _precip_mm(entry: dict) -> float | None:
    """Осадки за следующий час (предпочтительно) или 6 часов."""
    n1 = entry["data"].get("next_1_hours") or {}
    amt = (n1.get("details") or {}).get("precipitation_amount")
    if amt is not None:
        return float(amt)
    n6 = entry["data"].get("next_6_hours") or {}
    amt = (n6.get("details") or {}).get("precipitation_amount")
    if amt is not None:
        return float(amt)
    return None


def _symbol_code(entry: dict) -> str | None:
    """Код символа погоды: next_1_hours → next_6_hours → next_12_hours."""
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        block = entry["data"].get(key) or {}
        sym = (block.get("summary") or {}).get("symbol_code")
        if sym:
            return sym
    return None


def extract_current(met: dict) -> dict:
    """Нормализованная «текущая погода» из первой точки timeseries."""
    series = met["properties"]["timeseries"]
    if not series:
        return {}
    first = series[0]
    details = first["data"]["instant"]["details"]
    wind_ms = details.get("wind_speed")
    pressure_hpa = details.get("air_pressure_at_sea_level")
    
    symbol = _symbol_code(first)
    return {
        "time": first["time"],
        "temperature": details.get("air_temperature"),
        "humidity": details.get("relative_humidity"),
        "pressure_mmhg": round(pressure_hpa * 0.75006, 1) if pressure_hpa is not None else None,
        "cloud_cover": details.get("cloud_area_fraction"),
        "wind_speed_ms": round(wind_ms, 1) if wind_ms is not None else None,
        "wind_direction": details.get("wind_from_direction"),
        "precipitation_next_1h": _precip_mm(first),
        "symbol_code": symbol,
        "weather_code": SYMBOL_TO_WMO.get(symbol) if symbol else None,
    }


def extract_daily(met: dict, days: int = 7) -> list[dict]:
    """Сгруппировать timeseries по UTC-дате и вычислить дневные агрегаты."""
    series = met["properties"]["timeseries"]
    by_day: dict[str, list[dict]] = {}

    for entry in series:
        dt = _parse_time(entry["time"])
        date_str = dt.date().isoformat()
        by_day.setdefault(date_str, []).append(entry)

    # Отбрасываем прошлые даты (на случай, если MET вернул начало раньше «сейчас»).
    today = datetime.now(timezone.utc).date().isoformat()
    dates = sorted(d for d in by_day if d >= today)[:days]

    result: list[dict] = []
    for date_str in dates:
        entries = by_day[date_str]

        temperatures = [
            e["data"]["instant"]["details"].get("air_temperature")
            for e in entries
            if e["data"]["instant"]["details"].get("air_temperature") is not None
        ]
        if not temperatures:
            continue

        precip_values = [_precip_mm(e) for e in entries]
        precip_sum = round(sum(p for p in precip_values if p is not None), 2)

        # Ветер: максимум + направление в этот момент.
        wind_pairs = [
            (
                e["data"]["instant"]["details"].get("wind_speed"),
                e["data"]["instant"]["details"].get("wind_from_direction"),
            )
            for e in entries
        ]
        wind_pairs = [(s, d) for s, d in wind_pairs if s is not None]
        if wind_pairs:
            wind_max_ms, wind_dir_at_max = max(wind_pairs, key=lambda p: p[0])
            wind_max_ms = round(wind_max_ms, 1)
        else:
            wind_max_ms, wind_dir_at_max = None, None

        symbols = [s for s in (_symbol_code(e) for e in entries) if s]
        dominant_symbol = Counter(symbols).most_common(1)[0][0] if symbols else None
        weather_code = SYMBOL_TO_WMO.get(dominant_symbol) if dominant_symbol else None

        result.append({
            "date": date_str,
            "temperature_max": round(max(temperatures), 2),
            "temperature_min": round(min(temperatures), 2),
            "temperature_mean": round(sum(temperatures) / len(temperatures), 2),
            "precipitation_sum": precip_sum,
            "wind_speed_max": wind_max_ms,
            "wind_direction_dominant": wind_dir_at_max,
            "weather_code": weather_code,
            "symbol_code": dominant_symbol,
            "raw": {"entries_count": len(entries)},
        })

    return result


def persist_daily(lat: float, lon: float, daily_records: list[dict]) -> None:
    """Upsert дневных агрегатов в weather_daily."""
    if not daily_records:
        return
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for rec in daily_records:
                cur.execute(
                    """
                    insert into weather_daily
                        (latitude, longitude, date,
                         temperature_max, temperature_min, temperature_mean,
                         precipitation_sum, wind_speed_max,
                         wind_direction_dominant, weather_code, raw)
                    values
                        (%(lat)s, %(lon)s, %(date)s,
                         %(tmax)s, %(tmin)s, %(tmean)s,
                         %(precip)s, %(wmax)s,
                         %(wdir)s, %(wcode)s, %(raw)s)
                    on conflict (latitude, longitude, date) do update set
                        temperature_max         = excluded.temperature_max,
                        temperature_min         = excluded.temperature_min,
                        temperature_mean        = excluded.temperature_mean,
                        precipitation_sum       = excluded.precipitation_sum,
                        wind_speed_max          = excluded.wind_speed_max,
                        wind_direction_dominant = excluded.wind_direction_dominant,
                        weather_code            = excluded.weather_code,
                        raw                     = excluded.raw,
                        updated_at              = now()
                    """,
                    {
                        "lat": lat,
                        "lon": lon,
                        "date": rec["date"],
                        "tmax": rec["temperature_max"],
                        "tmin": rec["temperature_min"],
                        "tmean": rec["temperature_mean"],
                        "precip": rec["precipitation_sum"],
                        "wmax": rec["wind_speed_max"],
                        "wdir": rec["wind_direction_dominant"],
                        "wcode": rec["weather_code"],
                        "raw": json.dumps(rec["raw"], ensure_ascii=False),
                    },
                )
        conn.commit()

def extract_hourly(met: dict, limit: int = 216) -> list[dict]:
    """Извлечь почасовой ряд (температура, осадки, ветер) на ближайшие limit часов."""
    series = met["properties"]["timeseries"]
    result = []
    
    for entry in series[:limit]:
        details = entry["data"]["instant"]["details"]
        wind_ms = details.get("wind_speed")
        
        result.append({
            "time": entry["time"],
            "temperature_c": details.get("air_temperature"),
            "precipitation_mm": _precip_mm(entry) or 0.0,
            "wind_speed_ms": round(wind_ms, 1) if wind_ms is not None else None,
            "wind_direction_deg": details.get("wind_from_direction"),
        })
    return result