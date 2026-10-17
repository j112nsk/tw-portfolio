"""
Эндпоинты погодных данных: /geocode, /current, /forecast, /history.

Геокодинг выполняется внутри через зависимость resolve_city.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import resolve_city
from app.schemas import (
    CurrentWeather,
    ForecastDay,
    ForecastResponse,
    GeocodeResponse,
    HistoryDay,
    HistoryResponse,
    HourlyForecast,  # <--- Добавили сюда
)
from app.services.aggregator import extract_current, extract_daily, extract_hourly
from app.services.cache import get_or_fetch_history, get_or_fetch_met_forecast
from app.services.met_norway import MetNorwayError
from app.services.open_meteo_archive import OpenMeteoError
from app.wmo import describe

router = APIRouter()


@router.get(
    "/geocode",
    response_model=GeocodeResponse,
    tags=["weather"],
    summary="Найти населённый пункт",
    description="Возвращает координаты и метаданные населённого пункта по названию.",
)
def geocode_endpoint(
    name: str = Query(..., min_length=1, description="Название населённого пункта"),
) -> GeocodeResponse:
    from app.services.cache import get_or_fetch_geocode
    from app.services.nominatim import NominatimError

    try:
        geo = get_or_fetch_geocode(name)
    except NominatimError as exc:
        raise HTTPException(502, f"Сервис геокодинга недоступен: {exc}")
    if geo is None:
        raise HTTPException(404, f"Населённый пункт «{name}» не найден")
    return GeocodeResponse(
        city=geo["display_name"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
        country_code=geo["country_code"],
    )


@router.get(
    "/current",
    response_model=CurrentWeather,
    tags=["weather"],
    summary="Текущая погода",
    description="Текущие условия по населённому пункту (MET Norway, ближайший час).",
)
def current_endpoint(geo: dict = Depends(resolve_city)) -> CurrentWeather:
    try:
        met = get_or_fetch_met_forecast(geo["latitude"], geo["longitude"])
    except MetNorwayError as exc:
        raise HTTPException(502, f"MET Norway недоступен: {exc}")

    cur = extract_current(met)
    return CurrentWeather(
        city=geo["display_name"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
        timezone=geo.get("timezone", "UTC"),
        time=cur.get("time", ""),
        temperature_c=cur.get("temperature"),
        humidity_pct=cur.get("humidity"),
        pressure_mmhg=cur.get("pressure_mmhg"),
        cloud_cover_pct=cur.get("cloud_cover"),
        wind_speed_ms=cur.get("wind_speed_ms"),
        wind_direction_deg=cur.get("wind_direction"),
        precipitation_next_1h_mm=cur.get("precipitation_next_1h"),
        weather_code=cur.get("weather_code"),
        weather_description=describe(cur.get("weather_code")),
    )


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    tags=["weather"],
    summary="Прогноз по дням",
    description="Дневные агрегаты прогноза: max/min/mean температуры, осадки, ветер.",
)
def forecast_endpoint(
    days: int = Query(7, ge=1, le=9, description="Количество дней прогноза (1–9)"),
    geo: dict = Depends(resolve_city),
) -> ForecastResponse:
    try:
        met = get_or_fetch_met_forecast(geo["latitude"], geo["longitude"])
    except MetNorwayError as exc:
        raise HTTPException(502, f"MET Norway недоступен: {exc}")

    daily = extract_daily(met, days=days)
    hourly = extract_hourly(met, limit=48)
    return ForecastResponse(
        city=geo["display_name"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
        timezone=geo.get("timezone", "UTC"),
        hourly=[
            HourlyForecast(
                time=h["time"],
                temperature_c=h["temperature_c"],
                precipitation_mm=h["precipitation_mm"],
                wind_speed_ms=h["wind_speed_ms"], # <--- Должно быть ms
                wind_direction_deg=h["wind_direction_deg"],
            )
            for h in hourly
        ],
        daily=[
            ForecastDay(
                date=d["date"],
                temperature_max_c=d["temperature_max"],
                temperature_min_c=d["temperature_min"],
                temperature_mean_c=d["temperature_mean"],
                precipitation_sum_mm=d["precipitation_sum"],
                wind_speed_max_ms=d["wind_speed_max"],
                wind_direction_deg=d["wind_direction_dominant"],
                weather_code=d["weather_code"],
                weather_description=describe(d["weather_code"]),
            )
            for d in daily
        ],
    )


@router.get(
    "/history",
    response_model=HistoryResponse,
    tags=["weather"],
    summary="Исторические данные",
    description="Дневные агрегаты за период (Open-Meteo Archive). Требует дат в прошлом.",
)
def history_endpoint(
    start_date: date = Query(..., description="Начало периода (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Конец периода (YYYY-MM-DD)"),
    geo: dict = Depends(resolve_city),
) -> HistoryResponse:
    if start_date > end_date:
        raise HTTPException(422, "start_date не может быть позже end_date")
    if (end_date - start_date).days > 365:
        raise HTTPException(422, "Период не может превышать 365 дней")

    try:
        payload = get_or_fetch_history(
            geo["latitude"],
            geo["longitude"],
            start_date.isoformat(),
            end_date.isoformat(),
        )
    except OpenMeteoError as exc:
        raise HTTPException(502, f"Open-Meteo Archive недоступен: {exc}")

    daily = payload.get("daily", {}) or {}
    times = daily.get("time", []) or []
    tmax = daily.get("temperature_2m_max", []) or []
    tmin = daily.get("temperature_2m_min", []) or []
    precip = daily.get("precipitation_sum", []) or []
    wind = daily.get("wind_speed_10m_max", []) or []

    items = []
    for i, d in enumerate(times):
        items.append(
            HistoryDay(
                date=d,
                temperature_max_c=tmax[i] if i < len(tmax) else None,
                temperature_min_c=tmin[i] if i < len(tmin) else None,
                precipitation_sum_mm=precip[i] if i < len(precip) else None,
                wind_speed_max_ms=wind[i] if i < len(wind) else None,
            )
        )

    return HistoryResponse(
        city=geo["display_name"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
        timezone=geo.get("timezone", "UTC"),
        start_date=start_date,
        end_date=end_date,
        days=items,
    )