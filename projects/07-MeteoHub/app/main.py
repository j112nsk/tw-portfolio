"""
Точка входа FastAPI-приложения MeteoHub.

Запуск (из корня проекта):
    uvicorn app.main:app --reload

Swagger UI: http://127.0.0.1:8000/docs
ReDoc:      http://127.0.0.1:8000/redoc
"""
from __future__ import annotations

from fastapi import FastAPI

from app.routers import analytics, weather

app = FastAPI(
    title="MeteoHub API",
    version="0.1.0",
    description=(
        "REST API для получения текущей погоды, прогноза, истории "
        "и аналитики. Источники: MET Norway (прогноз), Open-Meteo Archive "
        "(история), Nominatim (геокодинг)."
    ),
)

app.include_router(weather.router)
app.include_router(analytics.router)


@app.get("/health", tags=["service"], summary="Проверка живости")
def health() -> dict:
    """Возвращает 200, если сервис запущен."""
    return {"status": "ok", "service": "MeteoHub API", "version": "0.1.0"}