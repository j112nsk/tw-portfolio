"""
Подключение к PostgreSQL для проекта MeteoHub.

Читает настройки из .env (libpq-имена: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD)
и предоставляет:
  - get_dsn()      — DSN-строку для psycopg
  - get_connection() — новое соединение (для скриптов и миграций)
  - get_pool()     — общий пул соединений (для FastAPI)

Правила проекта:
  DM-02 — все метки времени хранятся в UTC (timestamptz).
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки окружения. Читаются из .env в корне проекта."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- PostgreSQL (имена стандартные для libpq) ---
    pghost: str = "localhost"
    pgport: int = 5432
    pgdatabase: str = "meteohub"
    pguser: str = "meteohub_app"
    pgpassword: str = ""

    # --- REST API ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"

    # --- Open-Meteo ---
    open_meteo_forecast: str = "https://api.open-meteo.com/v1"
    open_meteo_archive: str = "https://archive-api.open-meteo.com/v1"
    open_meteo_geocoding: str = "https://geocoding-api.open-meteo.com/v1"

    # --- Кэш ---
    cache_ttl_geocode: int = 86_400
    cache_ttl_weather: int = 3_600


_settings: Settings | None = None
_pool: ConnectionPool | None = None


def get_settings() -> Settings:
    """Вернуть singleton-настройки (кэшируются после первого чтения)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_dsn() -> str:
    """Собрать DSN-строку psycopg из настроек .env."""
    s = get_settings()
    return (
        f"host={s.pghost} port={s.pgport} dbname={s.pgdatabase} "
        f"user={s.pguser} password={s.pgpassword}"
    )


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """Контекстный менеджер: одно соединение (для скриптов, миграций, тестов)."""
    with psycopg.connect(get_dsn()) as conn:
        yield conn


def get_pool() -> ConnectionPool:
    """Вернуть общий пул соединений (создаётся лениво, закрывается при выходе)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_dsn(),
            min_size=1,
            max_size=5,
            open=True,
        )
        atexit.register(_pool.close)
    return _pool