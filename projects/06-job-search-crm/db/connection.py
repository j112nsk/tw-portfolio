"""Подключение к базе данных.

Параметры подключения берутся из файла .env в корне проекта
(переменные PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD).
Библиотека psycopg читает эти переменные окружения сама.
"""
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def get_connection() -> psycopg.Connection:
    """Открывает соединение с базой. Изменения нужно фиксировать вызовом commit()."""
    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f"Не найден файл {ENV_FILE}. Скопируйте .env.example в .env и впишите пароль."
        )
    load_dotenv(ENV_FILE)
    return psycopg.connect(client_encoding="UTF8", connect_timeout=5)
