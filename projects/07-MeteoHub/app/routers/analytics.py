"""
Эндпоинт /analytics — сводка по дням прогноза.

Порядок работы:
  1. Загружаем/обновляем прогноз (побочно заполняется weather_daily).
  2. Читаем агрегаты из weather_daily через SQL.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import resolve_city
from app.schemas import AnalyticsItem, AnalyticsResponse
from app.services.analytics import get_analytics
from app.services.cache import get_or_fetch_met_forecast
from app.services.met_norway import MetNorwayError
from app.wmo import describe

router = APIRouter()


def _to_item(raw: dict | None) -> AnalyticsItem | None:
    if raw is None:
        return None
    return AnalyticsItem(
        date=raw["date"],
        value=raw["value"],
        unit=raw["unit"],
        weather_code=raw.get("weather_code"),
        weather_description=describe(raw.get("weather_code")),
    )


@router.get(
    "/analytics",
    response_model=AnalyticsResponse,
    tags=["analytics"],
    summary="Сводка по дням прогноза",
    description=(
        "Самый тёплый, самый холодный, самый дождливый и самый ветреный день "
        "за окно прогноза. Считается по таблице weather_daily."
    ),
)
def analytics_endpoint(
    days: int = Query(7, ge=1, le=9, description="Окно анализа (1–9 дней)"),
    geo: dict = Depends(resolve_city),
) -> AnalyticsResponse:
    try:
        get_or_fetch_met_forecast(geo["latitude"], geo["longitude"])
    except MetNorwayError as exc:
        raise HTTPException(502, f"MET Norway недоступен: {exc}")

    summary = get_analytics(geo["latitude"], geo["longitude"], days=days)
    if summary is None:
        raise HTTPException(
            503,
            "Аналитические данные пока недоступны. Повторите запрос "
            "через несколько секунд — прогноз уже загружается.",
        )

    return AnalyticsResponse(
        city=geo["display_name"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
        period_days=summary["period_days"],
        warmest=_to_item(summary["warmest"]),
        coldest=_to_item(summary["coldest"]),
        wettest=_to_item(summary["wettest"]),
        windiest=_to_item(summary["windiest"]),
    )