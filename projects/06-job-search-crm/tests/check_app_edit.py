"""Проверка правки полей, дат этапов и удаления процесса (US-05).

Все проверки в одной транзакции, которая в конце откатывается.

Запуск из корня проекта при активном виртуальном окружении:
    $env:PGDATABASE = "job_search_crm_demo"
    python -m tests.check_app_edit
"""
import sys
from datetime import date

import psycopg

from app import data
from db.connection import get_connection
from db.seed.load_demo_data import DEMO_DATABASE

results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, details: str = "") -> None:
    results.append((label, bool(condition)))
    print(("  [OK]   " if condition else "  [FAIL] ") + label
          + (f"  ({details})" if details and not condition else ""))


def expect_error(label: str, exc_types, callable_) -> None:
    try:
        callable_()
    except exc_types:
        check(label, True)
        return
    except Exception as error:                                  # noqa: BLE001
        check(label, False, f"ожидалось {exc_types}, получено {type(error).__name__}: {error}")
        return
    check(label, False, "ошибки не было")


def make_open(conn, *, initiator="applicant", company="Правка-тест") -> int:
    return data.create_process(
        direction_code="SA_BA", initiator=initiator,
        company_name=company, vacancy_title="Тестовая вакансия",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 1),
        vacancy_source_code="HH_RU" if initiator == "applicant" else None,
        apply_channel_code="HH_RU" if initiator == "applicant" else None,
        communication_channel_code="TELEGRAM", conn=conn,
    )


def scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def current_status(conn, pid: int) -> str:
    return scalar(conn, """
        select s.code from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (pid,))


def history_ids(conn, pid: int) -> list[int]:
    rows = conn.execute(
        "select id from process_status_history where process_id = %s "
        "order by recorded_at, id", (pid,)).fetchall()
    return [r[0] for r in rows]


def run(conn) -> None:
    print("\n1. Правка полей процесса, начатого откликом (US-05, критерий 1)")
    pid = make_open(conn)
    data.update_process_fields(
        pid,
        direction_code="TW",
        company_name="Обновлённая Компания",
        vacancy_title="Технический писатель",
        communication_channel_code="EMAIL",
        vacancy_source_code="COMPANY_SITE",
        apply_channel_code="EMAIL",
        vacancy_url="https://example.com/new",
        employer_type_code="OUTSTAFF",
        employment_format_code="CIVIL_CONTRACT",
        salary_from=200000, salary_to=250000,
        contact_name="Анна К.", contact_position="HR-менеджер",
        note="правка",
        conn=conn)
    row = conn.execute("""
        select d.code, p.company_name, p.vacancy_title, cc.code, vs.code, ac.code,
               et.code, ef.code, p.salary_from, p.salary_to, p.contact_name, p.note
          from job_processes p
          join directions d on d.id = p.direction_id
          join channels cc on cc.id = p.communication_channel_id
          left join vacancy_sources vs on vs.id = p.vacancy_source_id
          left join channels ac on ac.id = p.apply_channel_id
          left join employer_types et on et.id = p.employer_type_id
          left join employment_formats ef on ef.id = p.employment_format_id
         where p.id = %s
    """, (pid,)).fetchone()
    check("Все поля обновились",
          row == ("TW", "Обновлённая Компания", "Технический писатель", "EMAIL",
                  "COMPANY_SITE", "EMAIL", "OUTSTAFF", "CIVIL_CONTRACT",
                  200000, 250000, "Анна К.", "правка"),
          f"получено {row}")

    print("\n2. Правка входящего процесса")
    pid_emp = make_open(conn, initiator="employer", company="Входящий-правка")
    data.update_process_fields(
        pid_emp, direction_code="SA_BA", company_name="Входящий-2",
        vacancy_title="Аналитик", communication_channel_code="PHONE",
        note=None, conn=conn)
    check("Поля входящего процесса обновлены, источник и канал отклика остались пустыми",
          scalar(conn, "select vacancy_source_id is null and apply_channel_id is null "
                       "from job_processes where id = %s", (pid_emp,)) is True)

    print("\n3. Валидации при правке")
    expect_error("Applicant без источника вакансии", ValueError,
                 lambda: data.update_process_fields(
                     pid, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     apply_channel_code="HH_RU", conn=conn))

    expect_error("Employer с источником вакансии", ValueError,
                 lambda: data.update_process_fields(
                     pid_emp, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", conn=conn))

    expect_error("Вилка «от» > «до»", ValueError,
                 lambda: data.update_process_fields(
                     pid, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
                     salary_from=300000, salary_to=200000, conn=conn))

    expect_error("Некорректная ссылка", ValueError,
                 lambda: data.update_process_fields(
                     pid, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
                     vacancy_url="ftp://example.com/1", conn=conn))

    expect_error("Несуществующий код направления", ValueError,
                 lambda: data.update_process_fields(
                     pid, direction_code="NO_SUCH", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", apply_channel_code="HH_RU", conn=conn))

    expect_error("Несуществующий код типа работодателя (тихая вставка NULL закрыта)",
                 ValueError,
                 lambda: data.update_process_fields(
                     pid, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
                     employer_type_code="NO_SUCH", conn=conn))

    expect_error("Несуществующий процесс", ValueError,
                 lambda: data.update_process_fields(
                     10 ** 9, direction_code="SA_BA", company_name="X", vacancy_title="Y",
                     communication_channel_code="TELEGRAM",
                     vacancy_source_code="HH_RU", apply_channel_code="HH_RU", conn=conn))

    print("\n4. Правка даты этапа (D22)")
    pid2 = make_open(conn, company="Дата-правка")
    data.update_process_status(pid2, "TECH_INTERVIEW", date(2026, 10, 10), conn=conn)
    ids = history_ids(conn, pid2)
    first_id = ids[0]
    data.update_history_record(first_id, stage_date=date(2026, 9, 28), note="перенос",
                               conn=conn)
    row = conn.execute("select stage_date, note from process_status_history where id = %s",
                       (first_id,)).fetchone()
    check("Дата этапа и комментарий обновлены", row == (date(2026, 9, 28), "перенос"),
          f"получено {row}")
    check("Статус процесса не изменился (правка даты не влияет на порядок записей)",
          current_status(conn, pid2) == "TECH_INTERVIEW")

    expect_error("Несуществующая запись истории", ValueError,
                 lambda: data.update_history_record(10 ** 9, stage_date=date(2026, 10, 1),
                                                    conn=conn))

    print("\n5. Удаление записи истории (US-05, критерий 3)")
    ids = history_ids(conn, pid2)
    # удаляем первую запись (HR_INTERVIEW) — остаётся TECH_INTERVIEW, статус не меняется
    data.delete_history_record(ids[0], conn=conn)
    check("Запись удалена",
          scalar(conn, "select count(*) from process_status_history where process_id = %s",
                 (pid2,)) == 1)
    check("Текущий статус = TECH_INTERVIEW (последняя оставшаяся запись)",
          current_status(conn, pid2) == "TECH_INTERVIEW")

    print("\n6. Нельзя удалить единственную запись истории (INV-18)")
    pid3 = make_open(conn, company="Единственная")
    only_id = history_ids(conn, pid3)[0]
    expect_error("Удаление единственной записи отклоняется базой",
                 psycopg.errors.RestrictViolation,
                 lambda: data.delete_history_record(only_id, conn=conn))
    check("Запись не удалилась",
          scalar(conn, "select count(*) from process_status_history where process_id = %s",
                 (pid3,)) == 1)

    print("\n7. Удаление процесса каскадом (US-05, критерий 5)")
    pid4 = make_open(conn, company="Каскад-тест")
    data.update_process_status(pid4, "TECH_INTERVIEW", date(2026, 10, 10), conn=conn)
    conn.execute("""insert into test_assignments (process_id, status_id, received_on)
                    values (%s, (select id from statuses where code = 'HR_INTERVIEW'), %s)""",
                 (pid4, date(2026, 10, 2)))
    conn.execute("insert into skills (name) values ('Каскад-навык') on conflict do nothing")
    conn.execute("""insert into process_skills (process_id, skill_id)
                    select %s, id from skills where lower(name) = lower('Каскад-навык')""",
                 (pid4,))
    data.delete_process(pid4, conn=conn)
    check("Процесс удалён",
          scalar(conn, "select count(*) from job_processes where id = %s", (pid4,)) == 0)
    check("История, тестовые и связи с навыками удалены каскадом",
          scalar(conn, "select count(*) from process_status_history where process_id = %s", (pid4,)) == 0
          and scalar(conn, "select count(*) from test_assignments where process_id = %s", (pid4,)) == 0
          and scalar(conn, "select count(*) from process_skills where process_id = %s", (pid4,)) == 0)
    check("Сам навык остался в справочнике",
          scalar(conn, "select count(*) from skills where lower(name) = lower('Каскад-навык')") == 1)

    expect_error("Удаление несуществующего процесса", ValueError,
                 lambda: data.delete_process(10 ** 9, conn=conn))


def main() -> None:
    print("Проверка правки полей, дат этапов и удаления (US-05)")
    with get_connection() as conn:
        name = conn.execute("select current_database()").fetchone()[0]
        if name != DEMO_DATABASE:
            sys.exit(f"Проверка выполняется только на демонстрационной базе «{DEMO_DATABASE}», "
                     f"а подключение к «{name}». Задайте: $env:PGDATABASE = \"{DEMO_DATABASE}\"")
        with conn.transaction():
            run(conn)
            raise psycopg.Rollback()

    failed = [label for label, ok in results if not ok]
    print(f"\nИтого: проверок {len(results)}, успешно {len(results) - len(failed)}, ошибок {len(failed)}")
    if failed:
        print("Не пройдено:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("Правка и удаление работают как ожидается.")


if __name__ == "__main__":
    main()