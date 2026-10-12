"""Выполнение аналитических запросов из db/queries/ и печать результатов таблицами.

Запуск из корня проекта при активном виртуальном окружении:
    python -m db.run_queries                         все запросы, текущая дата
    python -m db.run_queries --only 02               только запрос, имя файла которого содержит «02»
    python -m db.run_queries --today 2026-10-11      задать «сегодняшнюю» дату (для запроса напоминаний)
    python -m db.run_queries --only 02 --initiator applicant --date-from 2026-07-01

Для демонстрационной базы предварительно задайте имя базы в этом же терминале:
    $env:PGDATABASE = "job_search_crm_demo"
Запросы только читают данные.
"""
import argparse
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from db.connection import get_connection

QUERIES_DIR = Path(__file__).resolve().parent / "queries"
NAME_PATTERN = re.compile(r"^(0[1-9]|[1-9]\d)-[a-z0-9-]+\.sql$")   # 00-... (проверки согласованности) не входит


def default_params(today: date) -> dict:
    """Параметры запросов; None означает «без фильтра»."""
    return {"today": today, "initiator": None, "date_from": None, "date_to": None, "source": None,
            "apply_channel": None, "employer_type": None, "employment_format": None}


def query_files(only: str | None = None) -> list[Path]:
    files = [p for p in sorted(QUERIES_DIR.glob("*.sql")) if NAME_PATTERN.match(p.name)]
    return [p for p in files if only is None or only in p.name]


def run_file(conn, path: Path, params: dict) -> tuple[list[str], list[tuple]]:
    """Выполняет запрос из файла; возвращает названия колонок и строки."""
    cursor = conn.execute(path.read_bytes().decode("utf-8-sig"), params)
    return [column.name for column in cursor.description], cursor.fetchall()


def format_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, date):
        return f"{value:%d.%m.%Y}"
    if isinstance(value, Decimal):
        return f"{value:f}"
    return str(value)


def print_table(columns: list[str], rows: list[tuple], limit: int) -> None:
    shown = rows[:limit]
    cells = [[format_value(v) for v in row] for row in shown]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    print("  " + "  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in cells:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(row, widths)))
    if len(rows) > limit:
        print(f"  ... показано {limit} из {len(rows)} строк (параметр --limit)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Выполнение аналитических запросов")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="ГГГГ-ММ-ДД")
    parser.add_argument("--only", help="часть имени файла запроса, например 02")
    parser.add_argument("--limit", type=int, default=25, help="сколько строк показывать (по умолчанию 25)")
    parser.add_argument("--initiator", choices=["applicant", "employer"])
    parser.add_argument("--date-from", type=date.fromisoformat, dest="date_from")
    parser.add_argument("--date-to", type=date.fromisoformat, dest="date_to")
    parser.add_argument("--source")
    parser.add_argument("--apply-channel", dest="apply_channel")
    parser.add_argument("--employer-type", dest="employer_type")
    parser.add_argument("--employment-format", dest="employment_format")
    args = parser.parse_args()

    params = default_params(args.today)
    for key in ("initiator", "date_from", "date_to", "source", "apply_channel", "employer_type", "employment_format"):
        params[key] = getattr(args, key)

    files = query_files(args.only)
    if not files:
        sys.exit("Подходящих файлов запросов не найдено.")

    with get_connection() as conn:
        database = conn.execute("select current_database()").fetchone()[0]
        print(f"База: {database}; сегодня: {args.today:%d.%m.%Y}")
        for path in files:
            columns, rows = run_file(conn, path, params)
            print(f"\n{path.name}: строк {len(rows)}")
            print_table(columns, rows, args.limit)


if __name__ == "__main__":
    main()
