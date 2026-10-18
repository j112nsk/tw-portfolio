"""
Геокодинг через OpenStreetMap Nominatim.

Возвращает координаты и метаданные населённого пункта.
Правила Nominatim: обязателен User-Agent с контактом, не чаще 1 запроса/сек.

Ошибки:
  - город не найден → None;
  - HTTP/сеть → NominatimError.
"""
from __future__ import annotations

import httpx

from db.connection import get_settings


class NominatimError(Exception):
    """Сервис Nominatim недоступен или вернул ошибку."""


def geocode(name: str) -> dict | None:
    """Найти населённый пункт по названию. Возвращает первый результат или None."""
    settings = get_settings()
    url = f"{settings.nominatim_base}/search"
    params = {
        "q": name,
        "format": "json",
        "limit": 1,
        "accept-language": "ru",
        "addressdetails": 1,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise NominatimError(
            f"Nominatim HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        raise NominatimError(f"Сетевая ошибка Nominatim: {exc}") from exc

    if not isinstance(data, list) or not data:
        return None

    item = data[0]
    # Нормализуем в единую форму (Nominatim даёт lat/lon строками).
    return {
        "name": item.get("name") or item.get("display_name", "").split(",")[0],
        "display_name": item.get("display_name", ""),
        "latitude": float(item["lat"]),
        "longitude": float(item["lon"]),
        "country_code": (item.get("address", {}).get("country_code") or "").upper() or None,
        "timezone": None,  # Nominatim не отдаёт; можно вычислять отдельно
        "raw": item,
    }
    
def search_cities(name: str, limit: int = 5) -> list[dict]:
    """Поиск населённых пунктов (возвращает список результатов для выпадающего списка)."""
    settings = get_settings()
    url = f"{settings.nominatim_base}/search"
    params = {
        "q": name,
        "format": "json",
        "limit": limit,
        "accept-language": "ru",
        "addressdetails": 1,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise NominatimError(f"Nominatim HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise NominatimError(f"Сетевая ошибка Nominatim: {exc}") from exc

    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        results.append({
            "name": item.get("name") or item.get("display_name", "").split(",")[0],
            "display_name": item.get("display_name", ""),
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
            "country_code": (item.get("address", {}).get("country_code") or "").upper() or None,
            "timezone": None,
            "raw": item,
        })
    return results    