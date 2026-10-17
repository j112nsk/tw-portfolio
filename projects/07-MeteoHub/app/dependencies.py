"""
Общие FastAPI-зависимости.

resolve_city(city) — единая точка разрешения названия населённого пункта
в координаты + метаданные. Используется во всех эндпоинтах, где есть
параметр city.

Коды ошибок:
  - 404 — населённый пункт не найден;
  - 502 — геокодер недоступен.
"""
from __future__ import annotations

from fastapi import HTTPException, Query

from app.services.cache import get_or_fetch_geocode
from app.services.nominatim import NominatimError


def resolve_city(
    city: str = Query(..., min_length=1, description="Название населённого пункта"),
) -> dict:
    """Найти координаты по названию города. Возвращает нормализованный dict."""
    try:
        geo = get_or_fetch_geocode(city)
    except NominatimError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Сервис геокодинга недоступен: {exc}",
        )
    if geo is None:
        raise HTTPException(
            status_code=404,
            detail=f"Населённый пункт «{city}» не найден",
        )
    return geo