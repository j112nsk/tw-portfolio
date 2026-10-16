"""
Применение SQL-миграций из db/schema/ в порядке имён файлов.

Использование:
    python -m db.migrate

Правила:
  - каждый файл применяется один раз; повторный запуск безопасен (idempotent),
    т.к. скрипты используют create ... if not exists;
  - журнал применённых файлов ведётся в таблице schema_migrations.
"""
from __future__ import annotations

import sys
from pathlib import Path

from db.connection import get_connection

SCHEMA_DIR = Path(__file__).parent / "schema"


def ensure_migrations_table(conn) -> None:
    """Создать служебную таблицу журнала миграций, если её ещё нет."""
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                filename    text        primary key,
                applied_at  timestamptz not null default now()
            )
            """
        )
    conn.commit()


def applied_files(conn) -> set[str]:
    """Множество уже применённых файлов миграций."""
    with conn.cursor() as cur:
        cur.execute("select filename from schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_file(conn, path: Path) -> None:
    """Применить один SQL-файл и записать его в журнал."""
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "insert into schema_migrations (filename) values (%s)",
            (path.name,),
        )
    conn.commit()
    print(f"  applied: {path.name}")


def main() -> int:
    """Точка входа: применить все неприменённые миграции."""
    if not SCHEMA_DIR.exists():
        print(f"Папка {SCHEMA_DIR} не найдена", file=sys.stderr)
        return 1

    files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not files:
        print("Нет SQL-файлов для применения")
        return 0

    with get_connection() as conn:
        ensure_migrations_table(conn)
        done = applied_files(conn)

        pending = [f for f in files if f.name not in done]
        if not pending:
            print("Все миграции уже применены")
            return 0

        print(f"К применению: {len(pending)} файл(ов)")
        for path in pending:
            apply_file(conn, path)

    print("Готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())