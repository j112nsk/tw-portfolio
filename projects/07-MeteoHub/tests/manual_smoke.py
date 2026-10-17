"""
Ручная проверка цепочки MeteoHub:
  Nominatim → MET Norway → агрегатор → Open-Meteo Archive.

Запуск из корня проекта:
    python -m tests.manual_smoke
"""
from __future__ import annotations

import time

from app.services.cache import (
    get_or_fetch_geocode,
    get_or_fetch_history,
    get_or_fetch_met_forecast,
)
from app.services.aggregator import extract_current, extract_daily
from app.services.met_norway import MetNorwayError
from app.services.nominatim import NominatimError
from app.services.open_meteo_archive import OpenMeteoError


def timed(label, func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start
    print(f"  {label}: {elapsed*1000:.1f} мс")
    return result


def main() -> None:
    city = "Новосибирск"

    print(f"1. Геокодинг: {city}")
    geo = timed("geocode (1-й)", get_or_fetch_geocode, city)
    if geo is None:
        print("   Город не найден — проверьте запрос")
        return
    lat, lon = float(geo["latitude"]), float(geo["longitude"])
    print(f"   → {geo['display_name']} ({lat}, {lon})")
    timed("geocode (2-й, кэш)", get_or_fetch_geocode, city)

    print("\n2. MET Norway: прогноз")
    met = timed("forecast (1-й)", get_or_fetch_met_forecast, lat, lon)
    series = met["properties"]["timeseries"]
    print(f"   Точек в timeseries: {len(series)}")
    timed("forecast (2-й, кэш)", get_or_fetch_met_forecast, lat, lon)

    print("\n3. Текущая погода (из MET Norway)")
    cur = extract_current(met)
    print(f"   Время (UTC): {cur['time']}")
    print(f"   Температура: {cur['temperature']} °C, ветер {cur['wind_speed_kmh']} км/ч, "
          f"влажность {cur['humidity']}%, WMO {cur['weather_code']} ({cur['symbol_code']})")

    print("\n4. Дневные агрегаты (7 дней)")
    daily = extract_daily(met, days=7)
    for d in daily:
        print(f"   {d['date']}: max {d['temperature_max']} °C, "
              f"min {d['temperature_min']} °C, "
              f"осадки {d['precipitation_sum']} мм, "
              f"ветер max {d['wind_speed_max']} км/ч, "
              f"WMO {d['weather_code']}")

    print("\n5. История Open-Meteo Archive")
    history = timed("history (1-й)", get_or_fetch_history, lat, lon,
                    "2025-10-01", "2025-10-07")
    print(f"   Дней в ответе: {len(history['daily']['time'])}")
    timed("history (2-й, кэш)", get_or_fetch_history, lat, lon,
          "2025-10-01", "2025-10-07")

    print("\nГотово.")


if __name__ == "__main__":
    try:
        main()
    except (MetNorwayError, NominatimError, OpenMeteoError) as exc:
        print(f"\nОшибка: {exc}")
        raise SystemExit(1)