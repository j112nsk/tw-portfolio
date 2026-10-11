"""Проверка согласованности данных по запросам из db/queries/00-integrity-checks.sql.

Запуск из корня проекта при активном виртуальном окружении:
    python -m db.check_integrity

Для демонстрационной базы предварительно задайте имя базы в этом же терминале:
    $env:PGDATABASE = "job_search_crm_demo"
Код возврата: 0 — нарушений нет, 1 — есть нарушения.
"""
import sys
from pathlib import Path

from db.connection import get_connection

SQL_FILE = Path(__file__).resolve().parent / "queries" / "00-integrity-checks.sql"


def main() -> None:
    sql = SQL_FILE.read_bytes().decode("utf-8-sig")
    with get_connection() as conn:
        database = conn.execute("select current_database()").fetchone()[0]
        processes = conn.execute("select count(*) from job_processes").fetchone()[0]
        violations = conn.execute(sql).fetchall()

    print(f"База: {database}; процессов: {processes}")
    if not violations:
        print("Нарушений согласованности не найдено.")
        return

    print(f"Найдено нарушений: {len(violations)}")
    for rule, process_id, company, details in violations:
        print(f"  [{rule}] процесс {process_id} ({company}): {details}")
    sys.exit(1)


if __name__ == "__main__":
    main()
