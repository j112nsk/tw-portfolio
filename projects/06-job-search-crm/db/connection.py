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
    """Открывает соединение с базой в режиме autocommit.

    autocommit=True нужен для записывающих функций приложения (app/data.py): когда они
    открывают собственное соединение (без параметра conn), при autocommit=False первый
    же SELECT запускал бы неявную транзакцию, а последующий блок `with conn.transaction():`
    превращался бы в savepoint. При закрытии соединения такая транзакция откатывалась бы,
    и данные не сохранялись. С autocommit=True каждый оператор вне блока коммитится сразу,
    а `with conn.transaction():` создаёт полноценную транзакцию BEGIN…COMMIT.

    Читающие запросы и вызовы с переданным снаружи соединением работают так же, как раньше.
    """
    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f"Не найден файл {ENV_FILE}. Скопируйте .env.example в .env и впишите пароль."
        )
    load_dotenv(ENV_FILE)
    return psycopg.connect(client_encoding="UTF8", connect_timeout=5, autocommit=True)
