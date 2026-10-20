"""Дымовая проверка базы данных: схема, справочники, ограничения и триггеры.

Запуск из корня проекта при активном виртуальном окружении:
    python -m tests.smoke_db

Все проверки выполняются в одной транзакции, которая в конце откатывается:
тестовые данные в базе не остаются.
"""
import sys
from datetime import date

import psycopg

from db.connection import get_connection

EXPECTED_TABLES = {
    "directions", "vacancy_sources", "channels", "employer_types", "employment_formats",
    "rejection_reasons", "statuses", "skills", "job_processes", "process_status_history",
    "process_skills", "profile_skills",
}
EXPECTED_TRIGGERS = {
    "job_processes_check_channels",
    "job_processes_protect_initiator",
    "process_status_history_check_rejection",
    "process_status_history_sync_status",
    "process_status_history_protect_last",
}

# Коды ошибок PostgreSQL (SQLSTATE)
NOT_NULL_VIOLATION = "23502"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FK_VIOLATION = "23503"
RESTRICT_VIOLATION = "23001"
GENERATED_ALWAYS = "428C9"

results: list[tuple[str, bool]] = []


# ---------------------------------------------------------------- помощники

def check(label: str, condition: bool, details: str = "") -> None:
    results.append((label, bool(condition)))
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f"  ({details})" if details else ""))


def section(title: str) -> None:
    print(f"\n{title}")


def scalar(conn: psycopg.Connection, sql: str, params=None):
    return conn.execute(sql, params).fetchone()[0]


def expect_error(conn: psycopg.Connection, label: str, sqlstate: str, sql: str, params=None) -> None:
    """Выполняет запрос, который должен завершиться ошибкой с заданным SQLSTATE.

    Запрос выполняется во вложенной транзакции (точка сохранения), поэтому ошибка не
    прерывает основную транзакцию.
    """
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as error:
        check(label, error.sqlstate == sqlstate, f"ожидался {sqlstate}, получен {error.sqlstate}: {error}")
    else:
        check(label, False, "ошибки не было")


def add_process(conn, initiator="applicant", company="Тест Компания", title="Системный аналитик",
                url="https://example.com/vacancy/1", direction="SA_BA", source="HH_RU",
                apply_channel="HH_RU", comm_channel="TELEGRAM", status="HR_INTERVIEW") -> int:
    """Создаёт процесс (без записи истории). У входящего источник и канал отклика пусты."""
    if initiator == "employer":
        source = None
        apply_channel = None
    return scalar(conn, """
        insert into job_processes
            (direction_id, initiator, company_name, vacancy_title, vacancy_url,
             vacancy_source_id, apply_channel_id, communication_channel_id, status_id)
        values
            ((select id from directions where code = %(direction)s), %(initiator)s,
             %(company)s, %(title)s, %(url)s,
             (select id from vacancy_sources where code = %(source)s),
             (select id from channels where code = %(apply_channel)s),
             (select id from channels where code = %(comm_channel)s),
             (select id from statuses where code = %(status)s))
        returning id
    """, {"direction": direction, "initiator": initiator, "company": company, "title": title,
          "url": url, "source": source, "apply_channel": apply_channel,
          "comm_channel": comm_channel, "status": status})


def add_history(conn, process_id: int, status: str, stage_date: date,
                reason: str | None = None) -> int:
    return scalar(conn, """
        insert into process_status_history
            (process_id, status_id, stage_date, rejection_reason_id)
        values
            (%(pid)s, (select id from statuses where code = %(status)s), %(stage_date)s,
             (select id from rejection_reasons where code = %(reason)s))
        returning id
    """, {"pid": process_id, "status": status, "stage_date": stage_date, "reason": reason})


def add_full_process(conn, status="HR_INTERVIEW", stage_date=date(2026, 10, 8), **kwargs) -> int:
    """Процесс с начальной записью истории (как создаёт его приложение)."""
    process_id = add_process(conn, status=status, **kwargs)
    add_history(conn, process_id, status, stage_date)
    return process_id


def current_status(conn, process_id: int) -> str:
    return scalar(conn, """
        select s.code from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (process_id,))


# ---------------------------------------------------------------- проверки

def check_structure(conn) -> None:
    section("1. Структура базы")
    tables = {row[0] for row in conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE'")}
    missing = EXPECTED_TABLES - tables
    check("Все 12 таблиц модели созданы", not missing, f"нет таблиц: {sorted(missing)}")

    triggers = {row[0] for row in conn.execute("select tgname from pg_trigger where not tgisinternal")}
    missing = EXPECTED_TRIGGERS - triggers
    check("Все 5 триггеров созданы", not missing, f"нет триггеров: {sorted(missing)}")

    print(f"  версия сервера: {scalar(conn, 'show server_version')}, "
          f"кодировка базы: {scalar(conn, 'show server_encoding')}")
    check("Кодировка базы UTF8", scalar(conn, "show server_encoding") == "UTF8")
    check("Строчные буквы кириллицы: lower('ООО Ромашка') = 'ооо ромашка'",
          scalar(conn, "select lower('ООО Ромашка')") == "ооо ромашка",
          "функция lower() не обрабатывает кириллицу; нужна другая локаль базы")


def check_reference_data(conn) -> None:
    section("2. Справочники")
    expected = {"directions": 2, "vacancy_sources": 4, "channels": 4, "employer_types": 3,
                "employment_formats": 2, "rejection_reasons": 5, "statuses": 11}
    for table, count in expected.items():
        actual = scalar(conn, f"select count(*) from {table}")
        check(f"{table}: {count} значений", actual == count, f"найдено {actual}")

    stages = scalar(conn, "select count(*) from statuses where kind = 'stage'")
    required = scalar(conn, "select count(*) from statuses where is_required_stage")
    in_funnel = scalar(conn, "select count(*) from statuses where in_funnel")
    check("Этапов 6; обязательных 3; участвуют в воронке 5 (без «Тестового задания»)",
          (stages, required, in_funnel) == (6, 3, 5),
          f"этапов {stages}, обязательных {required}, в воронке {in_funnel}")
    check("Каналом отклика можно назвать только 3 канала (телефон нельзя)",
          scalar(conn, "select count(*) from channels where is_apply_channel") == 3)


def check_status_sync(conn) -> None:
    section("3. Текущий статус процесса (триггер синхронизации)")
    pid = add_process(conn, status="HR_INTERVIEW")
    add_history(conn, pid, "HR_INTERVIEW", date(2026, 10, 8))
    check("После первой записи истории статус процесса = HR_INTERVIEW",
          current_status(conn, pid) == "HR_INTERVIEW")

    add_history(conn, pid, "TECH_INTERVIEW", date(2026, 10, 15))
    check("После записи TECH_INTERVIEW статус процесса = TECH_INTERVIEW",
          current_status(conn, pid) == "TECH_INTERVIEW")

    last_id = add_history(conn, pid, "OFFER", date(2026, 10, 24))
    check("Записи в одной транзакции (одинаковое recorded_at): побеждает последняя по id",
          current_status(conn, pid) == "OFFER")

    conn.execute("delete from process_status_history where id = %s", (last_id,))
    check("После удаления последней записи статус возвращается к предыдущему (TECH_INTERVIEW)",
          current_status(conn, pid) == "TECH_INTERVIEW")

    only_one = add_full_process(conn, company="Одна запись")
    expect_error(conn, "Единственную запись истории удалить нельзя (INV-18)", RESTRICT_VIOLATION,
                 "delete from process_status_history where process_id = %s", (only_one,))

    test_first = add_process(conn, company="Первым выдано тестовое", status="TEST_ASSIGNMENT")
    add_history(conn, test_first, "TEST_ASSIGNMENT", date(2026, 10, 5))
    in_funnel = scalar(conn, """
        select s.in_funnel from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (test_first,))
    check("Процесс, начатый с выдачи тестового: статус «Тестовое задание», в воронку не входит (D32)",
          current_status(conn, test_first) == "TEST_ASSIGNMENT" and in_funnel is False)


def check_constraints(conn) -> None:
    section("4. Ограничения таблиц")
    expect_error(conn, "Отклик соискателя без канала отклика не сохраняется (INV-02)", CHECK_VIOLATION,
                 """insert into job_processes
                        (direction_id, initiator, company_name, vacancy_title,
                         vacancy_source_id, communication_channel_id, status_id)
                    values ((select id from directions where code = 'SA_BA'), 'applicant', 'X', 'Y',
                            (select id from vacancy_sources where code = 'HH_RU'),
                            (select id from channels where code = 'TELEGRAM'),
                            (select id from statuses where code = 'HR_INTERVIEW'))""")

    expect_error(conn, "У входящего процесса не может быть источника вакансии (INV-02)", CHECK_VIOLATION,
                 """insert into job_processes
                        (direction_id, initiator, company_name, vacancy_title,
                         vacancy_source_id, communication_channel_id, status_id)
                    values ((select id from directions where code = 'SA_BA'), 'employer', 'X', 'Y',
                            (select id from vacancy_sources where code = 'HH_RU'),
                            (select id from channels where code = 'TELEGRAM'),
                            (select id from statuses where code = 'HR_INTERVIEW'))""")

    expect_error(conn, "Канал общения обязателен для обоих инициаторов (INV-03)", NOT_NULL_VIOLATION,
                 """insert into job_processes
                        (direction_id, initiator, company_name, vacancy_title, status_id)
                    values ((select id from directions where code = 'SA_BA'), 'employer', 'X', 'Y',
                            (select id from statuses where code = 'HR_INTERVIEW'))""")

    expect_error(conn, "Недопустимое значение инициатора не сохраняется (INV-01)", CHECK_VIOLATION,
                 """insert into job_processes
                        (direction_id, initiator, company_name, vacancy_title,
                         communication_channel_id, status_id)
                    values ((select id from directions where code = 'SA_BA'), 'robot', 'X', 'Y',
                            (select id from channels where code = 'TELEGRAM'),
                            (select id from statuses where code = 'HR_INTERVIEW'))""")

    no_url = add_process(conn, company="Без ссылки", url=None)
    check("Процесс без ссылки на вакансию создаётся (D31)", no_url is not None)

    employer_id = add_process(conn, initiator="employer", company="Входящая Компания",
                              direction="TW", title="Технический писатель")
    check("Входящий процесс без источника и канала отклика создаётся (INV-02)", employer_id is not None)

    expect_error(conn, "Ссылка не по шаблону http(s):// не сохраняется (INV-07)", CHECK_VIOLATION,
                 "update job_processes set vacancy_url = 'ftp://example.com/1' where id = %s", (no_url,))

    expect_error(conn, "Вилка «от» больше «до» не сохраняется (INV-05)", CHECK_VIOLATION,
                 "update job_processes set salary_from = 300000, salary_to = 200000 where id = %s", (no_url,))

    expect_error(conn, "Нулевая вилка не сохраняется (INV-05)", CHECK_VIOLATION,
                 "update job_processes set salary_from = 0 where id = %s", (no_url,))

    expect_error(conn, "Этап без признака участия в воронке не сохраняется (согласованность справочника статусов)",
                 CHECK_VIOLATION,
                 """insert into statuses (code, name_ru, sort_order, kind, stage_order, is_required_stage, in_funnel)
                    values ('X_TEST', 'Тест', 99, 'stage', 99, true, null)""")

    expect_error(conn, "Первичный ключ формирует база: явный id не принимается", GENERATED_ALWAYS,
                 "insert into directions (id, code, name_ru, sort_order) values (99, 'X_TEST', 'Тест', 9)")

    expect_error(conn, "Используемое значение справочника удалить нельзя (INV-15)", FK_VIOLATION,
                 "delete from directions where code = 'SA_BA'")


def check_triggers(conn) -> None:
    section("5. Триггеры")
    expect_error(conn, "Телефон нельзя указать каналом отклика при создании (INV-04)", CHECK_VIOLATION,
                 """insert into job_processes
                        (direction_id, initiator, company_name, vacancy_title,
                         vacancy_source_id, apply_channel_id, communication_channel_id, status_id)
                    values ((select id from directions where code = 'SA_BA'), 'applicant', 'X', 'Y',
                            (select id from vacancy_sources where code = 'HH_RU'),
                            (select id from channels where code = 'PHONE'),
                            (select id from channels where code = 'TELEGRAM'),
                            (select id from statuses where code = 'HR_INTERVIEW'))""")

    pid = add_full_process(conn, company="Отказ после интервью")
    expect_error(conn, "Телефон нельзя указать каналом отклика и при изменении (INV-04)", CHECK_VIOLATION,
                 "update job_processes set apply_channel_id = (select id from channels where code = 'PHONE') where id = %s",
                 (pid,))

    expect_error(conn, "Причина отказа у записи HR_INTERVIEW не допускается (INV-08)", CHECK_VIOLATION,
                 """insert into process_status_history
                        (process_id, status_id, stage_date, rejection_reason_id)
                    values (%s, (select id from statuses where code = 'HR_INTERVIEW'), %s,
                            (select id from rejection_reasons where code = 'NO_REASON'))""",
                 (pid, date(2026, 10, 9)))

    add_history(conn, pid, "REJECTED_BY_EMPLOYER", date(2026, 10, 12), reason="EXPERIENCE_MISMATCH")
    check("Причина отказа у записи REJECTED_BY_EMPLOYER принимается; статус процесса = REJECTED_BY_EMPLOYER",
          current_status(conn, pid) == "REJECTED_BY_EMPLOYER")

    expect_error(conn, "Инициатора процесса менять нельзя (INV-19)", RESTRICT_VIOLATION,
                 "update job_processes set initiator = 'employer' where id = %s", (pid,))


def check_skills(conn) -> None:
    section("6. Навыки")
    conn.execute("insert into skills (name) values ('Смоук-навык')")
    expect_error(conn, "Навык «смоук-навык» не добавляется, если есть «Смоук-навык» (INV-14)", UNIQUE_VIOLATION,
                 "insert into skills (name) values ('смоук-навык')")
    expect_error(conn, "Навык с пробелами по краям не добавляется", CHECK_VIOLATION,
                 "insert into skills (name) values (' BPMN')")


def check_cascade(conn) -> None:
    section("7. Удаление процесса (каскад)")
    pid = add_full_process(conn, company="Каскадное удаление")
    add_history(conn, pid, "TECH_INTERVIEW", date(2026, 10, 15))
    conn.execute("insert into skills (name) values ('UML') on conflict do nothing")
    conn.execute("""insert into process_skills (process_id, skill_id)
                    select %s, id from skills where name = 'UML'""", (pid,))

    conn.execute("delete from job_processes where id = %s", (pid,))
    history = scalar(conn, "select count(*) from process_status_history where process_id = %s", (pid,))
    skills = scalar(conn, "select count(*) from process_skills where process_id = %s", (pid,))
    check("Процесс удаляется вместе с историей (несмотря на защиту последней записи)", history == 0,
          f"записей истории: {history}")
    check("Вместе с процессом удалены связи с навыками", skills == 0, f"навыков: {skills}")
    check("Сам навык после удаления процесса остаётся в справочнике",
          scalar(conn, "select count(*) from skills where name = 'UML'") == 1)


# ---------------------------------------------------------------- запуск

def main() -> None:
    print("Дымовая проверка базы данных (все изменения откатываются)")
    with get_connection() as conn:
        with conn.transaction():
            check_structure(conn)
            check_reference_data(conn)
            check_status_sync(conn)
            check_constraints(conn)
            check_triggers(conn)
            check_skills(conn)
            check_cascade(conn)
            raise psycopg.Rollback()  # откатываем все тестовые данные

    failed = [label for label, ok in results if not ok]
    print(f"\nИтого: проверок {len(results)}, успешно {len(results) - len(failed)}, ошибок {len(failed)}")
    if failed:
        print("Не пройдено:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("Все проверки пройдены. Тестовые данные откатились.")


if __name__ == "__main__":
    main()