"""
Pydantic-схемы для REST API MeteoHub.

Единицы измерения зашиты в имена полей: _c — градусы Цельсия,
_mm — миллиметры, _kmh — км/ч, _hpa — гектопаскали, _deg — градусы,
_pct — проценты. Это делает ответы самоописательными и упрощает
документацию в Swagger.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class GeocodeResponse(BaseModel):
    """Результат геокодинга населённого пункта."""

    city: str = Field(..., description="Название (отображаемое имя из геокодера)")
    latitude: float = Field(..., description="Широта, WGS84")
    longitude: float = Field(..., description="Долгота, WGS84")
    country_code: str | None = Field(None, description="ISO 3166-1 alpha-2")


class CurrentWeather(BaseModel):
    """Текущая погода."""

    city: str
    latitude: float
    longitude: float
    timezone: str = Field(..., description="Часовой пояс (IANA), например Europe/Moscow")
    time: str = Field(..., description="Момент наблюдения, ISO 8601 UTC")
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_mmhg: float | None = None
    cloud_cover_pct: float | None = None
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    precipitation_next_1h_mm: float | None = None
    weather_code: int | None = None
    weather_description: str | None = None


class ForecastDay(BaseModel):
    """Один день прогноза."""

    date: date
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    temperature_mean_c: float | None = None
    precipitation_sum_mm: float | None = None
    wind_speed_max_ms: float | None = None
    wind_direction_deg: float | None = None
    weather_code: int | None = None
    weather_description: str | None = None


class HourlyForecast(BaseModel):
    """Один час прогноза."""
    time: str = Field(..., description="ISO 8601 UTC")
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    wind_speed_ms: float | None = None  # <--- Должно быть ms
    wind_direction_deg: float | None = None


class ForecastResponse(BaseModel):
    """Прогноз: почасовой + посуточный."""

    city: str
    latitude: float
    longitude: float
    timezone: str
    hourly: list[HourlyForecast]
    daily: list[ForecastDay]


class HistoryDay(BaseModel):
    """Один день истории (Open-Meteo Archive)."""

    date: date
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_sum_mm: float | None = None
    wind_speed_max_ms: float | None = None


class HistoryResponse(BaseModel):
    """История за период."""

    city: str
    latitude: float
    longitude: float
    timezone: str
    start_date: date
    end_date: date
    days: list[HistoryDay]


class AnalyticsItem(BaseModel):
    """Один аналитический показатель."""

    date: date
    value: float
    unit: str = Field(..., description="Единица измерения (°C, мм, км/ч)")
    weather_code: int | None = None
    weather_description: str | None = None


class AnalyticsResponse(BaseModel):
    """Сводка: самый тёплый / холодный / дождливый / ветреный день."""

    city: str
    latitude: float
    longitude: float
    timezone: str
    period_days: int
    warmest: AnalyticsItem | None = None
    coldest: AnalyticsItem | None = None
    wettest: AnalyticsItem | None = None
    windiest: AnalyticsItem | None = None