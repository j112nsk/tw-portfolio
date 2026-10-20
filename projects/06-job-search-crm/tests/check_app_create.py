"""Проверка создания процесса (US-01) на демонстрационной базе.

Все проверки выполняются в одной транзакции, которая в конце откатывается:
тестовые данные в базе не остаются.

Запуск из корня проекта при активном виртуальном окружении:
    $env:PGDATABASE = "job_search_crm_demo"
    python -m tests.check_app_create
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
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f"  ({details})" if details else ""))


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


def scalar(conn, sql: str, params=None):
    return conn.execute(sql, params).fetchone()[0]


def current_status(conn, pid: int) -> str:
    return scalar(conn, """
        select s.code from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (pid,))


def run(conn) -> None:
    print("\n1. Создание процесса, начатого откликом (US-01)")
    pid = data.create_process(
        direction_code="SA_BA", initiator="applicant",
        company_name="Тест Компания", vacancy_title="Системный аналитик",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
        communication_channel_code="TELEGRAM",
        conn=conn,
    )
    check("create_process вернул положительный id", isinstance(pid, int) and pid > 0, f"id={pid}")
    check("Процесс появился в job_processes",
          scalar(conn, "select count(*) from job_processes where id = %s", (pid,)) == 1)
    check("Создана ровно одна запись истории",
          scalar(conn, "select count(*) from process_status_history where process_id = %s", (pid,)) == 1)
    check("Текущий статус = HR_INTERVIEW (триггер синхронизации)", current_status(conn, pid) == "HR_INTERVIEW")

    print("\n2. Создание процесса, начатого работодателем (D11)")
    pid_emp = data.create_process(
        direction_code="TW", initiator="employer",
        company_name="Входящая Компания", vacancy_title="Технический писатель",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 21),
        communication_channel_code="TELEGRAM",
        conn=conn,
    )
    row = conn.execute("""select vacancy_source_id, apply_channel_id from job_processes where id = %s""",
                       (pid_emp,)).fetchone()
    check("У входящего процесса источник вакансии и канал отклика пусты (INV-02)",
          row[0] is None and row[1] is None)
    check("Текущий статус входящего процесса = HR_INTERVIEW", current_status(conn, pid_emp) == "HR_INTERVIEW")

    print("\n3. Процесс со стартом «Тестовое задание» (первым выдано тестовое, D32)")
    pid_test = data.create_process(
        direction_code="SA_BA", initiator="applicant",
        company_name="Тест Первым", vacancy_title="Аналитик",
        initial_status_code="TEST_ASSIGNMENT", initial_stage_date=date(2026, 10, 5),
        vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
        communication_channel_code="HH_RU",
        conn=conn,
    )
    check("Текущий статус = TEST_ASSIGNMENT (триггер)", current_status(conn, pid_test) == "TEST_ASSIGNMENT")
    rec = scalar(conn, "select count(*) from process_status_history where process_id = %s", (pid_test,))
    check("История содержит ровно одну запись (тестовое = этап, D32)", rec == 1, f"найдено {rec}")
    in_funnel = scalar(conn, """
        select s.in_funnel from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (pid_test,))
    check("TEST_ASSIGNMENT вне воронки (in_funnel = false)", in_funnel is False)

    print("\n4. Значения по умолчанию из последнего процесса")
    defaults = data.get_last_process_defaults(conn=conn)
    check("direction_code совпадает с направлением последнего созданного процесса",
          defaults["direction_code"] == "SA_BA", f"получено {defaults['direction_code']}")
    check("vacancy_source_code берётся из последнего applicant-процесса",
          defaults["vacancy_source_code"] == "HH_RU", f"получено {defaults['vacancy_source_code']}")
    check("apply_channel_code берётся из последнего applicant-процесса",
          defaults["apply_channel_code"] == "HH_RU", f"получено {defaults['apply_channel_code']}")
    check("communication_channel_code берётся из последнего процесса (id desc)",
          defaults["communication_channel_code"] == "HH_RU",
          f"получено {defaults['communication_channel_code']}")

    print("\n5. Валидации (приложение отвергает некорректный ввод)")
    expect_error("Пустое название компании", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="applicant",
        company_name="   ", vacancy_title="X",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
        communication_channel_code="TELEGRAM", conn=conn))

    expect_error("Applicant без источника вакансии", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="applicant",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        apply_channel_code="HH_RU", communication_channel_code="TELEGRAM", conn=conn))

    expect_error("Employer с источником вакансии", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        vacancy_source_code="HH_RU", communication_channel_code="TELEGRAM", conn=conn))

    expect_error("Пустой канал общения", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        communication_channel_code="", conn=conn))

    expect_error("Некорректная ссылка (ftp://)", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        communication_channel_code="TELEGRAM",
        vacancy_url="ftp://example.com/1", conn=conn))

    expect_error("Вилка «от» больше «до»", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        communication_channel_code="TELEGRAM",
        salary_from=300000, salary_to=200000, conn=conn))

    expect_error("Вилка «от» = 0", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
        communication_channel_code="TELEGRAM",
        salary_from=0, conn=conn))

    expect_error("Начальный статус — итог (SR1)", ValueError, lambda: data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="X", vacancy_title="Y",
        initial_status_code="OFFER_ACCEPTED", initial_stage_date=date(2026, 10, 20),
        communication_channel_code="TELEGRAM", conn=conn))

    print("\n6. Правила на уровне базы (триггер канала отклика, INV-04)")
    expect_error("Канал отклика PHONE (is_apply_channel = false)", psycopg.Error,
                 lambda: data.create_process(
                     direction_code="SA_BA", initiator="applicant",
                     company_name="X", vacancy_title="Y",
                     initial_status_code="HR_INTERVIEW", initial_stage_date=date(2026, 10, 20),
                     vacancy_source_code="HH_RU", apply_channel_code="PHONE",
                     communication_channel_code="TELEGRAM", conn=conn))

    print("\n7. Первая запись истории — этап, не итог (INV-09) сохраняется приложением")
    pid2 = data.create_process(
        direction_code="SA_BA", initiator="employer",
        company_name="Второй", vacancy_title="Аналитик",
        initial_status_code="TECH_INTERVIEW", initial_stage_date=date(2026, 10, 22),
        communication_channel_code="EMAIL", conn=conn)
    first_kind = scalar(conn, """
        select s.kind from process_status_history h
          join statuses s on s.id = h.status_id
         where h.process_id = %s
         order by h.recorded_at, h.id limit 1
    """, (pid2,))
    check("Первая запись истории процесса — этап (kind = 'stage')", first_kind == "stage",
          f"получено {first_kind}")


def main() -> None:
    print("Проверка создания процесса (US-01)")
    with get_connection() as conn:
        name = conn.execute("select current_database()").fetchone()[0]
        if name != DEMO_DATABASE:
            sys.exit(f"Проверка выполняется только на демонстрационной базе «{DEMO_DATABASE}», "
                     f"а подключение к «{name}». Задайте: $env:PGDATABASE = \"{DEMO_DATABASE}\"")
        with conn.transaction():
            run(conn)
            raise psycopg.Rollback()                        # откатываем тестовые данные

    failed = [label for label, ok in results if not ok]
    print(f"\nИтого: проверок {len(results)}, успешно {len(results) - len(failed)}, ошибок {len(failed)}")
    if failed:
        print("Не пройдено:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("Создание процесса работает как ожидается.")


if __name__ == "__main__":
    main()