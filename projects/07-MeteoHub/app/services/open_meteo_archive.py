"""
Исторические данные через Open-Meteo Archive API.

Используется только для истории (start_date..end_date). Прогноз — из MET Norway.
Формат ответа Open-Meteo: плоский JSON с массивами hourly/daily.
"""
from __future__ import annotations

import httpx

from db.connection import get_settings


class OpenMeteoError(Exception):
    """Open-Meteo Archive API недоступен или вернул ошибку."""


_DAILY_VARS = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "wind_speed_10m_max,weather_code"
)
_HOURLY_VARS = (
    "temperature_2m,precipitation,wind_speed_10m,wind_direction_10m"
)


def get_history(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """Исторические данные за период (YYYY-MM-DD .. YYYY-MM-DD)."""
    settings = get_settings()
    url = f"{settings.open_meteo_archive}/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": _HOURLY_VARS,
        "daily": _DAILY_VARS,
        "timezone": "auto",
        "wind_speed_unit": "ms",  # Просим м/с вместо км/ч по умолчанию
    }

    try:
        with httpx.Client(
            timeout=25.0,
            transport=httpx.HTTPTransport(retries=1),
        ) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise OpenMeteoError(
            f"Open-Meteo Archive HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        raise OpenMeteoError(f"Сетевая ошибка Open-Meteo Archive: {exc}") from exc

    if isinstance(data, dict) and data.get("error") is True:
        raise OpenMeteoError(f"Open-Meteo: {data.get('reason', 'неизвестная ошибка')}")

    return data