"""Проверка навыков вакансии и профиля навыков (US-11) и правил INV-14, INV-17.

Все проверки в одной транзакции с откатом.

Запуск из корня проекта при активном виртуальном окружении:
    $env:PGDATABASE = "job_search_crm_demo"
    python -m tests.check_app_skills
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


def scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def make_process(conn, *, initial="HR_INTERVIEW", initiator="applicant",
                 company="Навыки-тест") -> int:
    return data.create_process(
        direction_code="SA_BA", initiator=initiator,
        company_name=company, vacancy_title="Аналитик",
        initial_status_code=initial, initial_stage_date=date(2026, 10, 1),
        vacancy_source_code="HH_RU" if initiator == "applicant" else None,
        apply_channel_code="HH_RU" if initiator == "applicant" else None,
        communication_channel_code="TELEGRAM", conn=conn,
    )


def _raw_insert_skill_case(conn, name: str) -> None:
    """Прямой INSERT в обход функции — проверяем уникальность на уровне базы.

    Обёрнут в savepoint, чтобы ошибка не отравила внешнюю транзакцию.
    """
    with conn.transaction():
        conn.execute("insert into skills (name) values (%s)", (name,))


def run(conn) -> None:
    print("\n1. set_process_skills создаёт навыки и связи (US-11, критерий 3)")
    pid = make_process(conn)
    saved = data.set_process_skills(pid, ["SQL", "BPMN", "Jira"], conn=conn)
    check("Функция вернула нормализованный список",
          saved == ["SQL", "BPMN", "Jira"], f"получено {saved}")
    check("Навыки процесса сохранены",
          data.get_process_skills(pid, conn=conn) == ["BPMN", "Jira", "SQL"],
          f"получено {data.get_process_skills(pid, conn=conn)}")

    print("\n2. Нормализация: регистр и пробелы (INV-14)")
    data.set_process_skills(pid, ["  sql  ", "SQL", "Sql", ""], conn=conn)
    check("Различающиеся только регистром/пробелами — один навык",
          data.get_process_skills(pid, conn=conn) == ["SQL"],
          f"получено {data.get_process_skills(pid, conn=conn)}")

    print("\n3. Замена набора: старые связи снимаются, справочник не чистится")
    data.set_process_skills(pid, ["Git", "Docker"], conn=conn)
    check("Прежние навыки сняты",
          data.get_process_skills(pid, conn=conn) == ["Docker", "Git"])
    check("Значения SQL, BPMN, Jira остались в справочнике (INV-15)",
          scalar(conn, "select count(*) from skills where lower(name) in ('sql', 'bpmn', 'jira')") == 3)

    print("\n4. Пустой список очищает навыки процесса")
    data.set_process_skills(pid, [], conn=conn)
    check("Навыков у процесса нет", data.get_process_skills(pid, conn=conn) == [])

    print("\n5. set_profile_skills создаёт профиль направления (D3)")
    data.set_profile_skills("SA_BA", ["SQL", "BPMN", "UML"], conn=conn)
    check("Профиль SA_BA сохранён и отсортирован без учёта регистра",
          data.get_direction_profile_skills("SA_BA", conn=conn) == ["BPMN", "SQL", "UML"],
          f"получено {data.get_direction_profile_skills('SA_BA', conn=conn)}")

    print("\n6. Профили направлений независимы (US-11, критерий 6)")
    data.set_profile_skills("TW", ["Markdown", "DITA"], conn=conn)
    check("Профиль TW не затрагивает профиль SA_BA",
          data.get_direction_profile_skills("SA_BA", conn=conn) == ["BPMN", "SQL", "UML"])
    check("Профиль TW сохранён",
          data.get_direction_profile_skills("TW", conn=conn) == ["DITA", "Markdown"])

    print("\n7. Повторное добавление в профиль не создаёт дубликат (US-11, критерий 7)")
    data.set_profile_skills("SA_BA", ["SQL", "sql", " SQL ", "BPMN"], conn=conn)
    check("В профиле SA_BA ровно два навыка",
          data.get_direction_profile_skills("SA_BA", conn=conn) == ["BPMN", "SQL"],
          f"получено {data.get_direction_profile_skills('SA_BA', conn=conn)}")

    print("\n8. Подсказки по направлению (US-11, критерий 3)")
    pid2 = make_process(conn, company="Подсказки-1")
    data.set_process_skills(pid2, ["Python", "SQL", "Airflow"], conn=conn)
    pid3 = make_process(conn, company="Подсказки-2")
    data.set_process_skills(pid3, ["Kafka", "python"], conn=conn)

    sa_suggestions = data.get_direction_skill_suggestions("SA_BA", conn=conn)
    check("Подсказки SA_BA включают все встречавшиеся навыки",
          {"Python", "SQL", "Airflow", "Kafka"} <= set(sa_suggestions),
          f"получено {sa_suggestions}")
    check("Сортировка без учёта регистра",
          sa_suggestions == sorted(sa_suggestions, key=str.lower),
          f"получено {sa_suggestions}")

    # направление TW: подсказок из SA_BA быть не должно
    tw_suggestions = data.get_direction_skill_suggestions("TW", conn=conn)
    check("Подсказки TW не содержат навыков только из SA_BA",
          set(tw_suggestions).isdisjoint({"Airflow", "Kafka"}),
          f"получено {tw_suggestions}")

    print("\n9. Навыки хранятся независимо от текущего статуса (INV-17, D8)")
    pid4 = make_process(conn, initial="APPLIED", company="Только-тестовое")
    data.set_process_skills(pid4, ["RareSkill"], conn=conn)
    check("Навыки процесса без HR-интервью сохраняются",
          data.get_process_skills(pid4, conn=conn) == ["RareSkill"])

    print("\n10. INV-14 на уровне базы: уникальность без учёта регистра")
    expect_error("Прямой INSERT 'sql' при существующем 'SQL' отклоняется базой",
                 psycopg.errors.UniqueViolation,
                 lambda: _raw_insert_skill_case(conn, "sql"))

    print("\n11. Ошибки на несуществующих объектах")
    expect_error("set_profile_skills с несуществующим направлением",
                 ValueError,
                 lambda: data.set_profile_skills("NO_SUCH", ["X"], conn=conn))
    expect_error("set_process_skills с несуществующим процессом",
                 ValueError,
                 lambda: data.set_process_skills(10 ** 9, ["X"], conn=conn))


def main() -> None:
    print("Проверка навыков вакансии и профиля (US-11)")
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
    print("Навыки вакансии и профиль работают как ожидается.")


if __name__ == "__main__":
    main()