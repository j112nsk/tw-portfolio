"""
Клиент MET Norway (api.met.no) — прогноз Locationforecast 2.0.

Возвращает сырой GeoJSON с массивом properties.timeseries.
Структура точки:
    {
      "time": "ISO8601 UTC",
      "data": {
        "instant": {"details": {...}},
        "next_1_hours":  {"summary": {...}, "details": {"precipitation_amount": ...}},
        "next_6_hours":  {"summary": {...}, "details": {"precipitation_amount": ...}},
        "next_12_hours": {"summary": {...}, "details": {}}  # часто отсутствует
      }
    }

Правила:
  - User-Agent обязателен (иначе 403).
  - Таймаут 20 сек, retries=1.
  - Ошибки → MetNorwayError.
"""
from __future__ import annotations

import httpx

from db.connection import get_settings


class MetNorwayError(Exception):
    """MET Norway API недоступен или вернул ошибку."""


def get_forecast(lat: float, lon: float) -> dict:
    """Сырой GeoJSON прогноза MET Norway (до ~9 дней вперёд)."""
    settings = get_settings()
    url = f"{settings.met_norway_base}/weatherapi/locationforecast/2.0/compact"
    params = {"lat": lat, "lon": lon}
    headers = {"User-Agent": settings.nominatim_user_agent}

    try:
        with httpx.Client(
            timeout=20.0,
            transport=httpx.HTTPTransport(retries=1),
        ) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise MetNorwayError(
            f"MET Norway HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        raise MetNorwayError(f"Сетевая ошибка MET Norway: {exc}") from exc

    if not isinstance(data, dict) or "properties" not in data:
        raise MetNorwayError("MET Norway вернул неожиданный формат (нет properties)")

    return data