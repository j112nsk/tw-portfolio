"""Проверка слоя данных приложения (app/data.py) на демонстрационной базе.

Ожидаемые значения считаются независимо, Python-кодом, по воспроизводимому набору демо-данных.

Запуск из корня проекта при активном виртуальном окружении (дата та же, что при загрузке данных):
    $env:PGDATABASE = "job_search_crm_demo"
    python -m db.seed.load_demo_data --today 2026-10-11
    python -m tests.check_app_data --today 2026-10-11
"""
import argparse
import sys
from datetime import date, timedelta

from app import data
from db.seed.load_demo_data import DEMO_DATABASE, STAGES, generate_demo
from tests.check_queries_demo import STATUS_NAMES, derive

results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, details: str = "") -> None:
    results.append((label, bool(condition)))
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f"\n         {details}" if details else ""))


def expected_next(spec, today: date):
    """Ближайший запланированный этап открытого процесса: (дата, название) или None (SR13)."""
    if spec.history[-1].status not in STAGES:
        return None
    future = [(r.stage_date, STATUS_NAMES[r.status]) for r in spec.history
              if r.status in STAGES and r.stage_date >= today]
    return min(future, key=lambda item: item[0]) if future else None


def run_checks(specs, today: date) -> None:
    items = [derive(s) for s in specs]
    by_company = {s.company: s for s in specs}

    print("\n1. Справочники и сведения о базе")
    info = data.database_info()
    check("База распознана как демонстрационная", info["is_demo"] and info["name"] == DEMO_DATABASE)
    statuses = data.get_reference("statuses")
    check("Справочник статусов: 11 значений в порядке вывода",
          len(statuses) == 11 and statuses[0]["code"] == "APPLIED" and statuses[-1]["code"] == "NO_RESPONSE")
    check("Каналов отклика 3 (телефон не входит)", len(data.get_apply_channels()) == 3)

    print("\n2. Список процессов и фильтры")
    everything = data.list_processes(None, today)
    check("Без фильтров показаны все процессы", len(everything) == len(specs) == data.count_processes(),
          f"список {len(everything)}, ожидалось {len(specs)}")
    check("Фильтр «TW»: ровно процессы направления TW",
          len(data.list_processes({"directions": ["TW"]}, today)) == sum(1 for s in specs if s.direction == "TW"))
    check("Фильтр «открытые»",
          len(data.list_processes({"state": "open"}, today))
          == sum(1 for s in specs if s.history[-1].status in STAGES))
    check("Фильтр «закрытые»",
          len(data.list_processes({"state": "closed"}, today))
          == sum(1 for s in specs if s.history[-1].status not in STAGES))
    check("Фильтр «работодатель написал первым»",
          len(data.list_processes({"initiator": "employer"}, today))
          == sum(1 for s in specs if s.initiator == "employer"))
    rejected = {"REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME"}
    check("Фильтр по нескольким статусам (оба вида отказа)",
          len(data.list_processes({"statuses": sorted(rejected)}, today))
          == sum(1 for s in specs if s.history[-1].status in rejected))
    check("Фильтр по источнику hh.ru (только начатые откликом)",
          len(data.list_processes({"source": "HH_RU"}, today))
          == sum(1 for s in specs if s.source == "HH_RU"))
    check("Фильтр по типу работодателя и формату вместе",
          len(data.list_processes({"employer_type": "DIRECT", "employment_format": "LABOR_CONTRACT"}, today))
          == sum(1 for s in specs if s.employer_type == "DIRECT" and s.employment_format == "LABOR_CONTRACT"))
    window = {"date_from": today - timedelta(days=90), "date_to": today}
    check("Фильтр по периоду даты начала процесса",
          len(data.list_processes(window, today))
          == sum(1 for i in items if window["date_from"] <= i.start_date <= window["date_to"]))
    check("Поиск «демо» находит все процессы (в названиях компаний есть «(демо)»)",
          len(data.list_processes({"search": "демо"}, today)) == len(specs))
    check("Поиск по части названия компании без учёта регистра",
          len(data.list_processes({"search": specs[0].company[:6].upper()}, today)) >= 1)
    check("Поиск «%» не находит всё подряд (служебные символы экранируются)",
          len(data.list_processes({"search": "%"}, today)) == 0)
    check("Поиск несуществующего текста ничего не находит",
          len(data.list_processes({"search": "zzz-нет-такого"}, today)) == 0)

    print("\n3. Содержимое строк списка")
    wrong_next = [r["company_name"] for r in everything
                  if (expected_next(by_company[r["company_name"]], today) or (None, None))
                  != (r["next_date"], r["next_name"])]
    check("Ближайший этап: у открытых процессов верная дата и название, у закрытых пусто", not wrong_next,
          f"расхождения: {wrong_next[:3]}")
    last_dates = [r["last_record_date"] for r in everything]
    check("Список отсортирован по дате последней записи, новые первыми",
          all(a >= b for a, b in zip(last_dates, last_dates[1:])))
    wrong_last = [r["company_name"] for r in everything
                  if r["last_record_date"] != max(x.stage_date for x in by_company[r["company_name"]].history)]
    check("Дата последней записи равна максимальной дате этапа", not wrong_last, f"расхождения: {wrong_last[:3]}")
    start_by_company = {i.spec.company: i.start_date for i in items}
    wrong_start = [r["company_name"] for r in everything if r["start_date"] != start_by_company[r["company_name"]]]
    check("Дата начала процесса равна первой дате этапа (D21)", not wrong_start, f"расхождения: {wrong_start[:3]}")

    print("\n4. Карточка процесса")
    problems = []
    for row in everything:
        spec = by_company[row["company_name"]]
        card = data.get_process_card(row["id"])
        history = [(h["status"], h["stage_date"]) for h in card["history"]]
        expected_history = sorted(((STATUS_NAMES.get(r.status, r.status), r.stage_date) for r in spec.history),
                                  key=lambda item: item[1])
        if len(card["history"]) != len(spec.history):
            problems.append(f"{spec.company}: записей истории {len(card['history'])} из {len(spec.history)}")
        elif sorted(d for _, d in history) != [d for _, d in expected_history]:
            problems.append(f"{spec.company}: даты истории не совпали")
        if len(card["tests"]) != len(spec.tests):
            problems.append(f"{spec.company}: тестовых заданий {len(card['tests'])} из {len(spec.tests)}")
        if sorted(card["skills"], key=str.lower) != sorted(spec.skills, key=str.lower):
            problems.append(f"{spec.company}: набор навыков не совпал")
    check(f"У всех {len(everything)} процессов история, тестовые задания и навыки совпадают с эталоном",
          not problems, "\n         ".join(problems[:3]))
    check("Несуществующий процесс: карточка возвращает None", data.get_process_card(10 ** 9) is None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка слоя данных приложения")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(),
                        help="дата, с которой загружены демо-данные, ГГГГ-ММ-ДД")
    today = parser.parse_args().today
    specs = generate_demo(today)

    info = data.database_info()
    if info["name"] != DEMO_DATABASE:
        sys.exit(f"Проверка выполняется только на демонстрационной базе «{DEMO_DATABASE}», а подключение к "
                 f"«{info['name']}». Задайте: $env:PGDATABASE = \"{DEMO_DATABASE}\"")
    if data.count_processes() != len(specs):
        sys.exit(f"В базе {data.count_processes()} процессов, а ожидается {len(specs)}. Загрузите демо-данные "
                 f"командой python -m db.seed.load_demo_data --today {today.isoformat()}")
    print(f"Проверка слоя данных приложения: база {info['name']}, дата {today:%d.%m.%Y}")
    run_checks(specs, today)

    failed = [label for label, ok in results if not ok]
    print(f"\nИтого: проверок {len(results)}, успешно {len(results) - len(failed)}, ошибок {len(failed)}")
    if failed:
        print("Не пройдено:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("Слой данных приложения работает как ожидается.")


if __name__ == "__main__":
    main()
