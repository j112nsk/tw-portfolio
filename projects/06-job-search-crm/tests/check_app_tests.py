"""Проверка тестовых заданий (US-07) и правил INV-13 / SR13.

Все проверки в одной транзакции с откатом.

Запуск из корня проекта при активном виртуальном окружении:
    $env:PGDATABASE = "job_search_crm_demo"
    python -m tests.check_app_tests
"""
import sys
from datetime import date, timedelta

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


def scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def make_process(conn, *, initial="HR_INTERVIEW", initiator="applicant",
                 company="Тестовое-тест") -> int:
    return data.create_process(
        direction_code="SA_BA", initiator=initiator,
        company_name=company, vacancy_title="Аналитик",
        initial_status_code=initial, initial_stage_date=date(2026, 10, 1),
        vacancy_source_code="HH_RU" if initiator == "applicant" else None,
        apply_channel_code="HH_RU" if initiator == "applicant" else None,
        communication_channel_code="TELEGRAM", conn=conn,
    )


def run(conn) -> None:
    print("\n1. Добавление тестового задания (US-07, критерий 1)")
    pid = make_process(conn)
    test_id = data.add_test_assignment(pid, received_on=date(2026, 10, 2),
                                       due_on=date(2026, 10, 9),
                                       result_note="принято к работе", conn=conn)
    check("add_test_assignment вернул положительный id", isinstance(test_id, int) and test_id > 0)

    row = conn.execute("""
        select t.received_on, t.due_on, t.submitted_on, t.result_note, s.code
          from test_assignments t join statuses s on s.id = t.status_id
         where t.id = %s
    """, (test_id,)).fetchone()
    check("Поля сохранены",
          row == (date(2026, 10, 2), date(2026, 10, 9), None, "принято к работе", "HR_INTERVIEW"),
          f"получено {row}")
    check("status_id = текущий статус на момент получения (SR7)",
          row[4] == "HR_INTERVIEW")

    print("\n2. Тестовое без срока (DQ5)")
    test_nodue = data.add_test_assignment(pid, received_on=date(2026, 10, 3), conn=conn)
    row = conn.execute("select due_on from test_assignments where id = %s", (test_nodue,)).fetchone()
    check("Тестовое без срока сохраняется (due_on = NULL)", row[0] is None)

    print("\n3. Проверки INV-13")
    expect_error("Срок сдачи раньше даты получения",
                 ValueError,
                 lambda: data.add_test_assignment(pid, received_on=date(2026, 10, 10),
                                                  due_on=date(2026, 10, 5), conn=conn))

    # На уровне базы INV-13 тоже проверяется. Запрос идёт напрямую, поэтому его
    # нужно обернуть в savepoint (conn.transaction): иначе отравленной окажется
    # вся внешняя транзакция, и последующие проверки получат InFailedSqlTransaction.
    def _raw_insert_invalid_due():
        with conn.transaction():
            conn.execute("""
                insert into test_assignments (process_id, status_id, received_on, due_on)
                values (%s, (select id from statuses where code = 'HR_INTERVIEW'), %s, %s)
            """, (pid, date(2026, 10, 10), date(2026, 10, 5)))

    expect_error("БД отвергает срок сдачи раньше получения напрямую",
                 psycopg.errors.CheckViolation,
                 _raw_insert_invalid_due)

    print("\n4. Правка тестового задания (US-07, критерий 4)")
    data.update_test_assignment(test_id, received_on=date(2026, 10, 2),
                                due_on=date(2026, 10, 12), result_note="продлён срок",
                                conn=conn)
    row = conn.execute("select due_on, result_note from test_assignments where id = %s",
                       (test_id,)).fetchone()
    check("Срок и комментарий обновлены", row == (date(2026, 10, 12), "продлён срок"),
          f"получено {row}")

    expect_error("Правка с некорректной датой сдачи",
                 ValueError,
                 lambda: data.update_test_assignment(test_id, received_on=date(2026, 10, 10),
                                                     submitted_on=date(2026, 10, 5), conn=conn))

    expect_error("Несуществующее тестовое",
                 ValueError,
                 lambda: data.update_test_assignment(10 ** 9, received_on=date(2026, 10, 1),
                                                     conn=conn))

    print("\n5. Отметка «сдано» (US-07, критерий 2)")
    data.mark_test_submitted(test_id, submitted_on=date(2026, 10, 10),
                             result_note="сдано в срок", conn=conn)
    row = conn.execute("select submitted_on, result_note from test_assignments where id = %s",
                       (test_id,)).fetchone()
    check("Дата сдачи и результат сохранены", row == (date(2026, 10, 10), "сдано в срок"),
          f"получено {row}")

    expect_error("Дата сдачи раньше получения",
                 ValueError,
                 lambda: data.mark_test_submitted(test_id, submitted_on=date(2026, 9, 1),
                                                  conn=conn))

    print("\n6. SR13: запланировано/не запланировано (интеграция со списком напоминаний)")
    pid2 = make_process(conn, company="SR13-тест")
    # тестовое со сроком в будущем — считается запланированным
    t_future = data.add_test_assignment(pid2, received_on=date(2026, 10, 1),
                                        due_on=date.today() + timedelta(days=3),
                                        conn=conn)
    # тестовое без срока — не считается запланированным (SR13, DQ5)
    data.add_test_assignment(pid2, received_on=date(2026, 10, 1), conn=conn)
    # несданное с уже прошедшим сроком — тоже не считается (получено раньше срока)
    data.add_test_assignment(pid2, received_on=date(2026, 9, 1),
                             due_on=date(2026, 9, 30), conn=conn)

    scheduled = scalar(conn, """
        select count(*) from test_assignments
         where process_id = %s and submitted_on is null
           and due_on is not null and due_on >= current_date
    """, (pid2,))
    check("Только тестовое со сроком в будущем считается запланированным",
          scheduled == 1, f"получено {scheduled}")

    data.mark_test_submitted(t_future, submitted_on=date.today(), conn=conn)
    scheduled_after = scalar(conn, """
        select count(*) from test_assignments
         where process_id = %s and submitted_on is null
           and due_on is not null and due_on >= current_date
    """, (pid2,))
    check("Сданное тестовое больше не считается запланированным",
          scheduled_after == 0, f"получено {scheduled_after}")

    print("\n7. Несколько тестовых у одного процесса")
    pid3 = make_process(conn, company="Много-тестов")
    data.add_test_assignment(pid3, received_on=date(2026, 10, 1), due_on=date(2026, 10, 5), conn=conn)
    data.add_test_assignment(pid3, received_on=date(2026, 10, 8), conn=conn)
    tests = data.get_process_tests(pid3, conn=conn)
    check("get_process_tests возвращает оба задания, в порядке получения",
          len(tests) == 2 and tests[0]["received_on"] < tests[1]["received_on"],
          f"получено {[(t['received_on']) for t in tests]}")

    print("\n8. Удаление тестового задания (US-07, критерий 4)")
    data.delete_test_assignment(test_id, conn=conn)
    check("Задание удалено",
          scalar(conn, "select count(*) from test_assignments where id = %s", (test_id,)) == 0)

    expect_error("Удаление несуществующего тестового", ValueError,
                 lambda: data.delete_test_assignment(10 ** 9, conn=conn))

    print("\n9. Создание процесса со стартом «Отклик» и тестовым (US-01, критерий 5)")
    # тестовое создаётся автоматически при create_process; убеждаемся, что get_process_tests его видит
    pid4 = data.create_process(
        direction_code="SA_BA", initiator="applicant",
        company_name="Отклик-тест", vacancy_title="Аналитик",
        initial_status_code="APPLIED", initial_stage_date=date(2026, 10, 5),
        test_due_on=date(2026, 10, 12),
        vacancy_source_code="HH_RU", apply_channel_code="HH_RU",
        communication_channel_code="HH_RU", conn=conn)
    tests = data.get_process_tests(pid4, conn=conn)
    check("Автосозданное тестовое видно через get_process_tests",
          len(tests) == 1 and tests[0]["due_on"] == date(2026, 10, 12),
          f"получено {tests}")


def main() -> None:
    print("Проверка тестовых заданий (US-07)")
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
    print("Тестовые задания работают как ожидается.")


if __name__ == "__main__":
    main()