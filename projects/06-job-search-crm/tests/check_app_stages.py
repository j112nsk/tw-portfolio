"""Проверка смены статуса (US-04) и закрытия процесса (US-06).

Все проверки выполняются в одной транзакции, которая в конце откатывается.

Запуск из корня проекта при активном виртуальном окружении:
    $env:PGDATABASE = "job_search_crm_demo"
    python -m tests.check_app_stages
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


def expect_no_error(label: str, callable_, expected_warning_codes=None):
    try:
        result = callable_()
    except Exception as error:                                  # noqa: BLE001
        check(label, False, f"неожиданная ошибка {type(error).__name__}: {error}")
        return None
    if expected_warning_codes is not None:
        codes = {code for code, _ in result}
        check(label, codes == set(expected_warning_codes),
              f"ожидались {expected_warning_codes}, получены {codes}")
    else:
        check(label, True)
    return result


def scalar(conn, sql: str, params=None):
    return conn.execute(sql, params).fetchone()[0]


def current_status(conn, pid: int) -> str:
    return scalar(conn, """
        select s.code from job_processes p join statuses s on s.id = p.status_id where p.id = %s
    """, (pid,))


def history_count(conn, pid: int) -> int:
    return scalar(conn, "select count(*) from process_status_history where process_id = %s", (pid,))


def make_open(conn, *, initial="HR_INTERVIEW", direction="SA_BA", initiator="applicant",
              company="Статус-тест", stage_date=date(2026, 10, 1)) -> int:
    return data.create_process(
        direction_code=direction, initiator=initiator,
        company_name=company, vacancy_title="Тестовая вакансия",
        initial_status_code=initial, initial_stage_date=stage_date,
        vacancy_source_code="HH_RU" if initiator == "applicant" else None,
        apply_channel_code="HH_RU" if initiator == "applicant" else None,
        communication_channel_code="TELEGRAM", conn=conn,
    )


def run(conn) -> None:
    print("\n1. Типичный переход HR → TECH")
    pid = make_open(conn)
    expect_no_error("Обновление без предупреждений",
                    lambda: data.update_process_status(pid, "TECH_INTERVIEW",
                                                       date(2026, 10, 8), conn=conn),
                    expected_warning_codes=[])
    check("Текущий статус = TECH_INTERVIEW (триггер)", current_status(conn, pid) == "TECH_INTERVIEW")
    check("История процесса содержит 2 записи", history_count(conn, pid) == 2)

    print("\n2. Нетипичный переход: возврат на более ранний этап")
    warnings = data.check_atypical_transition(pid, "HR_INTERVIEW", conn=conn)
    codes = {code for code, _ in warnings}
    check("check_atypical_transition возвращает RETURN_TO_EARLIER_STAGE",
          "RETURN_TO_EARLIER_STAGE" in codes, f"получено {codes}")

    expect_error("update_process_status без confirm_atypical=True отклоняется", ValueError,
                 lambda: data.update_process_status(pid, "HR_INTERVIEW",
                                                    date(2026, 10, 10), conn=conn))
    check("Записи не появилось (было 2)", history_count(conn, pid) == 2)

    expect_no_error("update_process_status с confirm_atypical=True проходит",
                    lambda: data.update_process_status(pid, "HR_INTERVIEW", date(2026, 10, 10),
                                                       confirm_atypical=True, conn=conn))
    check("Текущий статус = HR_INTERVIEW", current_status(conn, pid) == "HR_INTERVIEW")
    check("История содержит 3 записи", history_count(conn, pid) == 3)

    print("\n3. Нетипичный переход: пропуск обязательного этапа")
    pid2 = make_open(conn)
    warnings = data.check_atypical_transition(pid2, "OFFER", conn=conn)
    codes = {code for code, _ in warnings}
    check("check_atypical_transition возвращает SKIP_REQUIRED_STAGE",
          "SKIP_REQUIRED_STAGE" in codes, f"получено {codes}")

    expect_error("Пропуск обязательного этапа без подтверждения отклоняется", ValueError,
                 lambda: data.update_process_status(pid2, "OFFER", date(2026, 10, 15), conn=conn))

    expect_no_error("Пропуск обязательного этапа с подтверждением проходит",
                    lambda: data.update_process_status(pid2, "OFFER", date(2026, 10, 15),
                                                       confirm_atypical=True, conn=conn))
    check("Текущий статус = OFFER", current_status(conn, pid2) == "OFFER")

    print("\n4. Закрытие: причина обязательна при HR-интервью в истории (SR9)")
    expect_error("REJECTED_BY_EMPLOYER без причины отклоняется", ValueError,
                 lambda: data.close_process(pid2, "REJECTED_BY_EMPLOYER",
                                            date(2026, 10, 20), conn=conn))

    expect_error("Несуществующая причина отклоняется", ValueError,
                 lambda: data.close_process(pid2, "REJECTED_BY_EMPLOYER", date(2026, 10, 20),
                                            rejection_reason_code="NOT_A_REASON", conn=conn))

    print("\n5. Закрытие: OFFER_ACCEPTED без OFFER в истории — предупреждение")
    pid3 = make_open(conn)
    warnings = data.check_atypical_transition(pid3, "OFFER_ACCEPTED", conn=conn)
    codes = {code for code, _ in warnings}
    check("check_atypical_transition возвращает OFFER_OUTCOME_WITHOUT_OFFER",
          "OFFER_OUTCOME_WITHOUT_OFFER" in codes, f"получено {codes}")

    expect_error("OFFER_ACCEPTED без подтверждения отклоняется", ValueError,
                 lambda: data.close_process(pid3, "OFFER_ACCEPTED", date(2026, 10, 20), conn=conn))

    expect_no_error("OFFER_ACCEPTED с подтверждением проходит",
                    lambda: data.close_process(pid3, "OFFER_ACCEPTED", date(2026, 10, 20),
                                               confirm_atypical=True, conn=conn))
    check("Текущий статус = OFFER_ACCEPTED", current_status(conn, pid3) == "OFFER_ACCEPTED")

    print("\n6. Изменение статуса после OFFER_ACCEPTED")
    expect_error("Любое изменение после OFFER_ACCEPTED требует подтверждения", ValueError,
                 lambda: data.close_process(pid3, "REJECTED_BY_EMPLOYER", date(2026, 10, 21),
                                            rejection_reason_code="OTHER", conn=conn))
    warnings = data.check_atypical_transition(pid3, "REJECTED_BY_EMPLOYER", conn=conn)
    codes = {code for code, _ in warnings}
    check("check_atypical_transition возвращает CHANGE_AFTER_FINAL_OFFER",
          "CHANGE_AFTER_FINAL_OFFER" in codes, f"получено {codes}")

    print("\n7. Возврат закрытого процесса в работу")
    pid4 = make_open(conn)
    data.close_process(pid4, "NO_RESPONSE", date(2026, 10, 10), conn=conn)
    check("Процесс закрыт итогом NO_RESPONSE", current_status(conn, pid4) == "NO_RESPONSE")

    expect_error("Установка этапа у закрытого процесса требует подтверждения", ValueError,
                 lambda: data.update_process_status(pid4, "HR_INTERVIEW",
                                                    date(2026, 10, 12), conn=conn))

    warnings = data.check_atypical_transition(pid4, "HR_INTERVIEW", conn=conn)
    codes = {code for code, _ in warnings}
    check("check_atypical_transition возвращает REOPEN_CLOSED_PROCESS",
          "REOPEN_CLOSED_PROCESS" in codes, f"получено {codes}")

    expect_no_error("Возврат в работу с подтверждением проходит",
                    lambda: data.update_process_status(pid4, "HR_INTERVIEW", date(2026, 10, 12),
                                                       confirm_atypical=True, conn=conn))
    check("Текущий статус снова HR_INTERVIEW", current_status(conn, pid4) == "HR_INTERVIEW")

    print("\n8. Причина недопустима для NO_RESPONSE / OFFER_ACCEPTED / OFFER_DECLINED (INV-08)")
    pid5 = make_open(conn)
    expect_error("NO_RESPONSE с причиной отклоняется", ValueError,
                 lambda: data.close_process(pid5, "NO_RESPONSE", date(2026, 10, 10),
                                            rejection_reason_code="OTHER", conn=conn))

    print("\n9. Разделение: update_process_status только для этапов; close_process — только для итогов")
    expect_error("update_process_status с итогом отклоняется", ValueError,
                 lambda: data.update_process_status(pid5, "NO_RESPONSE",
                                                    date(2026, 10, 10), conn=conn))
    expect_error("close_process с этапом отклоняется", ValueError,
                 lambda: data.close_process(pid5, "HR_INTERVIEW",
                                            date(2026, 10, 10), conn=conn))

    print("\n10. Повторная установка того же статуса (SR12: два технических собеседования)")
    pid6 = make_open(conn)
    data.update_process_status(pid6, "TECH_INTERVIEW", date(2026, 10, 8), conn=conn)
    data.update_process_status(pid6, "TECH_INTERVIEW", date(2026, 10, 15), conn=conn)
    count = scalar(conn, """
        select count(*) from process_status_history h
          join statuses s on s.id = h.status_id
         where h.process_id = %s and s.code = 'TECH_INTERVIEW'
    """, (pid6,))
    check("Две записи TECH_INTERVIEW в истории", count == 2, f"получено {count}")

    print("\n11. Закрытие с корректной причиной")
    pid7 = make_open(conn)
    data.update_process_status(pid7, "TECH_INTERVIEW", date(2026, 10, 8), conn=conn)
    data.close_process(pid7, "REJECTED_BY_EMPLOYER", date(2026, 10, 15),
                       rejection_reason_code="EXPERIENCE_MISMATCH", conn=conn)
    row = conn.execute("""
        select rr.code from process_status_history h
          join statuses s on s.id = h.status_id
          left join rejection_reasons rr on rr.id = h.rejection_reason_id
         where h.process_id = %s
         order by h.recorded_at desc, h.id desc limit 1
    """, (pid7,)).fetchone()
    check("Причина отказа сохранена в последней записи",
          row is not None and row[0] == "EXPERIENCE_MISMATCH", f"получено {row}")
    check("Текущий статус = REJECTED_BY_EMPLOYER",
          current_status(conn, pid7) == "REJECTED_BY_EMPLOYER")


def main() -> None:
    print("Проверка смены статуса (US-04) и закрытия процесса (US-06)")
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
    print("Смена статуса и закрытие процесса работают как ожидается.")


if __name__ == "__main__":
    main()