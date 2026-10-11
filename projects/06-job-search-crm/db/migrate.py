"""Применение SQL-миграций из папки db/schema/ по порядку номеров.

Запуск из корня проекта при активном виртуальном окружении:
    python -m db.migrate            применить все новые миграции
    python -m db.migrate --status   показать состояние миграций

Правила:
  * файл миграции называется NNN_описание.sql (три цифры, нижний регистр);
  * каждый файл применяется один раз, целиком, в одной транзакции;
  * применённый файл менять нельзя: изменение схемы оформляется новым файлом;
  * при ошибке транзакция откатывается и остальные файлы не применяются.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

import psycopg

from db.connection import get_connection

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
NAME_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

CREATE_TRACKING_TABLE = """
create table if not exists schema_migrations (
    version     text        primary key,
    file_name   text        not null,
    checksum    text        not null,
    applied_at  timestamptz not null default now()
)
"""


def find_migrations() -> list[tuple[str, Path]]:
    """Возвращает пары (номер, путь) в порядке возрастания номера."""
    found = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        match = NAME_PATTERN.match(path.name)
        if not match:
            print(f"Пропущен файл с неподходящим именем: {path.name}")
            continue
        found.append((match.group(1), path))
    versions = [version for version, _ in found]
    if len(versions) != len(set(versions)):
        sys.exit("Ошибка: в db/schema есть файлы с одинаковым номером.")
    return found


def file_checksum(path: Path) -> str:
    """Контрольная сумма файла; переводы строк нормализуются, чтобы CRLF и LF давали одно значение."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def read_sql(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def applied_migrations(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    rows = conn.execute("select version, file_name, checksum from schema_migrations").fetchall()
    return {version: (file_name, checksum) for version, file_name, checksum in rows}


def show_status(conn: psycopg.Connection, migrations: list[tuple[str, Path]]) -> None:
    applied = applied_migrations(conn)
    for version, path in migrations:
        if version not in applied:
            mark = "не применена"
        elif applied[version][1] != file_checksum(path):
            mark = "применена, НО ФАЙЛ ИЗМЕНЁН"
        else:
            mark = "применена"
        print(f"{path.name:40} {mark}")


def apply_pending(conn: psycopg.Connection, migrations: list[tuple[str, Path]]) -> None:
    applied = applied_migrations(conn)

    # Применённые файлы менять нельзя: сначала проверяем контрольные суммы.
    for version, path in migrations:
        if version in applied and applied[version][1] != file_checksum(path):
            sys.exit(f"Ошибка: файл {path.name} изменён после применения. Создайте новую миграцию.")

    pending = [(version, path) for version, path in migrations if version not in applied]
    if not pending:
        print("Новых миграций нет: база данных актуальна.")
        return

    for version, path in pending:
        print(f"Применяю {path.name} ...", end=" ", flush=True)
        try:
            conn.execute(read_sql(path))
            conn.execute(
                "insert into schema_migrations (version, file_name, checksum) values (%s, %s, %s)",
                (version, path.name, file_checksum(path)),
            )
            conn.commit()
        except psycopg.Error as error:
            conn.rollback()
            print("ОШИБКА")
            print(f"  {error}")
            sys.exit(1)
        print("готово")


def main() -> None:
    parser = argparse.ArgumentParser(description="Применение SQL-миграций")
    parser.add_argument("--status", action="store_true", help="показать состояние миграций и выйти")
    args = parser.parse_args()

    migrations = find_migrations()
    if not migrations:
        sys.exit(f"В папке {SCHEMA_DIR} нет файлов миграций.")

    try:
        with get_connection() as conn:
            conn.execute(CREATE_TRACKING_TABLE)
            conn.commit()
            if args.status:
                show_status(conn, migrations)
            else:
                apply_pending(conn, migrations)
    except (psycopg.OperationalError, FileNotFoundError) as error:
        sys.exit(f"Не удалось подключиться к базе данных: {error}")


if __name__ == "__main__":
    main()
