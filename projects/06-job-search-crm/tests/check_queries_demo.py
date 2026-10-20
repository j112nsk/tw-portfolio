"""Сверка аналитических запросов с независимым расчётом на Python (демонстрационная база).

Идея: набор демо-данных воспроизводим (db/seed/load_demo_data.py), поэтому для него можно
посчитать ожидаемые показатели Python-кодом и сравнить с результатами SQL-запросов из db/queries/.
Совпадение двух независимых реализаций подтверждает и запросы, и правила расчёта.

Запуск из корня проекта при активном виртуальном окружении (дата в обеих командах одинаковая):
    $env:PGDATABASE = "job_search_crm_demo"
    python -m db.seed.load_demo_data --today 2026-10-20
    python -m tests.check_queries_demo --today 2026-10-20
"""
import argparse
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from db.connection import get_connection
from db.run_queries import QUERIES_DIR, default_params, run_file
from db.seed.load_demo_data import (APPLY_CHANNELS, DEMO_DATABASE, DIRECTIONS, FUNNEL_STAGES,
                                    PROFILE_SKILLS, REJECTIONS, SOURCES, STAGES, ProcessSpec,
                                    generate_demo)

STAGE_ORDER = {code: number for number, code in enumerate(STAGES, start=1)}
STATUS_NAMES = {"HR_INTERVIEW": "HR-интервью",
                "TEST_ASSIGNMENT": "Тестовое задание",
                "TECH_INTERVIEW": "Техническое собеседование",
                "TEAM_MEETING": "Знакомство с командой",
                "SECURITY_CHECK": "СБ",
                "OFFER": "Оффер"}

results: list[tuple[str, bool]] = []


# ---------------------------------------------------------------- расчёт на Python

@dataclass
class Item:
    spec: ProcessSpec
    start_date: date
    max_funnel_order: int  # максимум stage_order только по этапам, входящим в воронку (SR11)

    @property
    def reached_hr(self) -> bool:
        return self.max_funnel_order >= STAGE_ORDER["HR_INTERVIEW"]

    @property
    def reached_tech(self) -> bool:
        return self.max_funnel_order >= STAGE_ORDER["TECH_INTERVIEW"]

    @property
    def reached_offer(self) -> bool:
        return self.max_funnel_order >= STAGE_ORDER["OFFER"]

    @property
    def had_team(self) -> bool:
        return any(r.status == "TEAM_MEETING" for r in self.spec.history)

    @property
    def had_security(self) -> bool:
        return any(r.status == "SECURITY_CHECK" for r in self.spec.history)


def derive(spec: ProcessSpec) -> Item:
    """Строит Item: дата начала — по всем этапам (DQ7), max_order — только по in_funnel (SR11)."""
    all_stage_dates = [r.stage_date for r in spec.history if r.status in STAGE_ORDER]
    start_date = min(all_stage_dates)
    funnel_orders = [STAGE_ORDER[r.status] for r in spec.history
                     if r.status in FUNNEL_STAGES]
    max_funnel_order = max(funnel_orders) if funnel_orders else 0
    return Item(spec, start_date, max_funnel_order)


def pct(part: int, whole: int) -> Decimal | None:
    if not whole:
        return None
    return (Decimal(100) * part / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round1(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round0(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def apply_filters(items: list[Item], params: dict) -> list[Item]:
    result = []
    for it in items:
        s = it.spec
        if params.get("initiator") and s.initiator != params["initiator"]:
            continue
        if params.get("date_from") and it.start_date < params["date_from"]:
            continue
        if params.get("date_to") and it.start_date > params["date_to"]:
            continue
        if params.get("source") and s.source != params["source"]:
            continue
        if params.get("apply_channel") and s.apply_channel != params["apply_channel"]:
            continue
        if params.get("employer_type") and s.employer_type != params["employer_type"]:
            continue
        if params.get("employment_format") and s.employment_format != params["employment_format"]:
            continue
        result.append(it)
    return result


def expect_reminders(specs: list[ProcessSpec], today: date) -> Counter:
    rows: Counter = Counter()
    for s in specs:
        if s.history[-1].status not in STAGE_ORDER:        # процесс закрыт
            continue
        events = [(r.stage_date, "stage", STATUS_NAMES[r.status]) for r in s.history
                  if r.status in STAGE_ORDER and r.stage_date >= today]
        if not events:
            last_stage = max(r.stage_date for r in s.history if r.status in STAGE_ORDER)
            rows[("no_planned_stage", last_stage, s.company, "none", "Нет запланированного этапа",
                  (today - last_stage).days)] += 1
            continue
        for event_date, kind, name in events:
            if event_date > today + timedelta(days=7):
                continue
            group = "today_tomorrow" if event_date <= today + timedelta(days=1) else "next_7_days"
            rows[(group, event_date, s.company, kind, name, None)] += 1
    return rows


def expect_funnel(items: list[Item]) -> dict:
    scopes: dict[str, list[Item]] = {}
    for it in items:
        scopes.setdefault(it.spec.direction, []).append(it)
    if items:
        scopes["ALL"] = list(items)
    rows = {}
    for scope, group in scopes.items():
        n_hr = sum(i.reached_hr for i in group)
        n_tech = sum(i.reached_tech for i in group)
        n_offer = sum(i.reached_offer for i in group)
        rows[(scope,)] = (len(group), n_hr, n_tech,
                          sum(i.had_team for i in group), sum(i.had_security for i in group), n_offer,
                          pct(n_tech, n_hr), pct(n_offer, n_tech), pct(n_offer, n_hr))
    return rows


def expect_days(items: list[Item]) -> dict:
    collected: dict[tuple[str, str], list[int]] = {}
    for it in items:
        first: dict[str, date] = {}
        for r in it.spec.history:
            first[r.status] = min(first.get(r.status, r.stage_date), r.stage_date)
        pairs = []
        if "HR_INTERVIEW" in first and "TECH_INTERVIEW" in first:
            pairs.append(("HR_TO_TECH", (first["TECH_INTERVIEW"] - first["HR_INTERVIEW"]).days))
        if "TECH_INTERVIEW" in first and "OFFER" in first:
            pairs.append(("TECH_TO_OFFER", (first["OFFER"] - first["TECH_INTERVIEW"]).days))
        for pair, days in pairs:
            for scope in (it.spec.direction, "ALL"):
                collected.setdefault((scope, pair), []).append(days)
    rows = {}
    for key, days in collected.items():
        valid = [d for d in days if d >= 0]
        rows[key] = (len(valid),
                     round1(Decimal(sum(valid)) / len(valid)) if valid else None,
                     round1(statistics.median(valid)) if valid else None,
                     len(days) - len(valid))
    return rows


def expect_sources(items: list[Item]) -> dict:
    rows = {}
    for direction in DIRECTIONS:
        applicants = [i for i in items if i.spec.direction == direction and i.spec.initiator == "applicant"]
        incoming = sum(1 for i in items if i.spec.direction == direction and i.spec.initiator == "employer")
        total = len(applicants)
        for dimension, values, getter in (("SOURCE", SOURCES, lambda s: s.source),
                                          ("APPLY_CHANNEL", APPLY_CHANNELS, lambda s: s.apply_channel)):
            for value in values:
                group = [i for i in applicants if getter(i.spec) == value]
                n_tech = sum(i.reached_tech for i in group)
                n_offer = sum(i.reached_offer for i in group)
                rows[(direction, dimension, value)] = (len(group), pct(len(group), total), n_tech,
                                                       pct(n_tech, len(group)), n_offer,
                                                       pct(n_offer, len(group)), incoming)
    return rows


def expect_slices(items: list[Item]) -> dict:
    groups: dict[tuple, list[Item]] = {}
    for it in items:
        s, d = it.spec, it.spec.direction
        groups.setdefault((d, "COMM_CHANNEL", s.comm_channel, None), []).append(it)
        if s.initiator == "applicant":
            groups.setdefault((d, "APPLY_X_COMM", s.apply_channel, s.comm_channel), []).append(it)
        groups.setdefault((d, "EMPLOYER_TYPE", s.employer_type or "NOT_SPECIFIED", None), []).append(it)
        groups.setdefault((d, "EMPLOYMENT_FORMAT", s.employment_format or "NOT_SPECIFIED", None), []).append(it)
    rows = {}
    for key, group in groups.items():
        n_tech = sum(i.reached_tech for i in group)
        n_offer = sum(i.reached_offer for i in group)
        rows[key] = (len(group), n_tech, pct(n_tech, len(group)), n_offer, pct(n_offer, len(group)))
    return rows


def expect_rejections(items: list[Item]) -> dict:
    counts: Counter = Counter()
    for it in items:
        last = it.spec.history[-1]
        if last.status in REJECTIONS and last.reason is not None:
            counts[(it.spec.direction, last.status, last.reason)] += 1
    totals: Counter = Counter()
    for (direction, outcome, _), n in counts.items():
        totals[(direction, outcome)] += n
    return {key: (n, pct(n, totals[(key[0], key[1])])) for key, n in counts.items()}


def expect_skills(items: list[Item]) -> dict:
    rows = {}
    for direction in DIRECTIONS:
        sample = [i for i in items if i.spec.direction == direction and i.reached_hr and i.spec.skills]
        counts = Counter(skill for i in sample for skill in i.spec.skills)
        for skill, n in counts.items():
            rows[(direction, skill)] = (n, pct(n, len(sample)), skill in PROFILE_SKILLS[direction], len(sample))
    return rows


def expect_salaries(items: list[Item]) -> dict:
    mids: dict[str, list[Decimal]] = {}
    for it in items:
        s = it.spec
        if s.salary_from is None and s.salary_to is None:
            continue
        low = s.salary_from if s.salary_from is not None else s.salary_to
        high = s.salary_to if s.salary_to is not None else s.salary_from
        for scope in (s.direction, "ALL"):
            mids.setdefault(scope, []).append(Decimal(low + high) / 2)
    rows = {}
    for scope, values in mids.items():
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        rows[(scope,)] = (len(values), round0(ordered[0]), round0(median), round0(ordered[-1]))
    return rows


# ---------------------------------------------------------------- сравнение

def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal("0.05")
    return a == b


def to_dict(columns: list[str], rows: list[tuple], key_columns: list[str], value_columns: list[str]) -> dict:
    index = {name: i for i, name in enumerate(columns)}
    return {tuple(row[index[c]] for c in key_columns): tuple(row[index[c]] for c in value_columns)
            for row in rows}


def check(label: str, condition: bool, details: str = "") -> None:
    results.append((label, bool(condition)))
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f"\n         {details}" if details else ""))


def compare_dicts(label: str, expected: dict, actual: dict) -> None:
    problems = []
    for key in sorted(set(expected) | set(actual), key=str):
        if key not in actual:
            problems.append(f"нет строки {key}; ожидалось {expected[key]}")
        elif key not in expected:
            problems.append(f"лишняя строка {key}: {actual[key]}")
        elif not all(same(a, b) for a, b in zip(expected[key], actual[key])) or len(expected[key]) != len(actual[key]):
            problems.append(f"{key}: ожидалось {expected[key]}, получено {actual[key]}")
    check(f"{label} (строк: {len(expected)})", not problems, "\n         ".join(problems[:4]))


def compare_counters(label: str, expected: Counter, actual: Counter) -> None:
    problems = []
    for key in sorted(set(expected) | set(actual), key=str):
        if expected[key] != actual[key]:
            problems.append(f"{key}: ожидалось {expected[key]}, получено {actual[key]}")
    check(f"{label} (строк: {sum(expected.values())})", not problems, "\n         ".join(problems[:4]))


# ---------------------------------------------------------------- запуск

def run_checks(conn, specs: list[ProcessSpec], today: date) -> None:
    items = [derive(s) for s in specs]
    base = default_params(today)

    def query(name: str, **filters):
        params = {**base, **filters}
        columns, rows = run_file(conn, QUERIES_DIR / name, params)
        return columns, rows, params

    print("\n1. Напоминания (Q4)")
    columns, rows, _ = query("01-reminders.sql")
    index = {c: i for i, c in enumerate(columns)}
    actual = Counter(tuple(r[index[c]] for c in ("group_code", "event_date", "company_name", "event_kind",
                                                  "event_name", "days_since_last_stage")) for r in rows)
    compare_counters("Напоминания: три группы, события и дни без этапа", expect_reminders(specs, today), actual)

    print("\n2. Воронка (Q1)")
    for label, filters in (
            ("без фильтров", {}),
            ("только начатые откликом", {"initiator": "applicant"}),
            ("только входящие", {"initiator": "employer"}),
            ("источник hh.ru", {"source": "HH_RU"}),
            ("последние 90 дней", {"date_from": today - timedelta(days=90), "date_to": today})):
        columns, rows, params = query("02-funnel.sql", **filters)
        compare_dicts(f"Воронка, {label}",
                      expect_funnel(apply_filters(items, params)),
                      to_dict(columns, rows, ["scope"],
                              ["n_total", "n_hr", "n_tech", "n_team", "n_security", "n_offer",
                               "pct_tech_of_hr", "pct_offer_of_tech", "pct_offer_of_hr"]))

    print("\n3. Дни между этапами (Q2)")
    for label, filters in (("без фильтров", {}), ("только начатые откликом", {"initiator": "applicant"})):
        columns, rows, params = query("03-days-between-stages.sql", **filters)
        compare_dicts(f"Дни между этапами, {label}", expect_days(apply_filters(items, params)),
                      to_dict(columns, rows, ["scope", "pair"], ["n", "avg_days", "median_days", "excluded_negative"]))

    print("\n4. Источники и каналы отклика (Q3, Q9)")
    for label, filters in (("без фильтров", {}), ("последние 90 дней", {"date_from": today - timedelta(days=90)})):
        columns, rows, params = query("04-sources-and-channels.sql", **filters)
        compare_dicts(f"Источники и каналы, {label}", expect_sources(apply_filters(items, params)),
                      to_dict(columns, rows, ["direction", "dimension", "value_code"],
                              ["n_processes", "share_pct", "n_tech", "pct_tech", "n_offer", "pct_offer",
                               "incoming_excluded"]))

    print("\n5. Срезы: канал общения, тип работодателя, формат (Q12, Q13)")
    for label, filters in (("без фильтров", {}), ("только прямой работодатель", {"employer_type": "DIRECT"})):
        columns, rows, params = query("05-slices.sql", **filters)
        compare_dicts(f"Срезы, {label}", expect_slices(apply_filters(items, params)),
                      to_dict(columns, rows, ["direction", "dimension", "value_1", "value_2"],
                              ["n_processes", "n_tech", "pct_tech", "n_offer", "pct_offer"]))

    print("\n6. Причины отказов (Q8)")
    columns, rows, params = query("06-rejection-reasons.sql")
    compare_dicts("Причины отказов", expect_rejections(apply_filters(items, params)),
                  to_dict(columns, rows, ["direction", "outcome_code", "reason_code"], ["n_processes", "share_pct"]))

    print("\n7. Навыки (Q5, Q6)")
    columns, rows, params = query("07-skills.sql")
    compare_dicts("Рейтинг навыков и пробелы", expect_skills(apply_filters(items, params)),
                  to_dict(columns, rows, ["direction", "skill"], ["n_processes", "share_pct", "in_profile", "n_sample"]))

    print("\n8. Зарплатные вилки (Q7)")
    for label, filters in (("без фильтров", {}), ("только входящие", {"initiator": "employer"})):
        columns, rows, params = query("08-salaries.sql", **filters)
        compare_dicts(f"Вилки, {label}", expect_salaries(apply_filters(items, params)),
                      to_dict(columns, rows, ["scope"], ["n", "min_mid", "median_mid", "max_mid"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Сверка аналитических запросов с расчётом на Python")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(),
                        help="дата, с которой загружены демо-данные, ГГГГ-ММ-ДД")
    today = parser.parse_args().today
    specs = generate_demo(today)

    with get_connection() as conn:
        database = conn.execute("select current_database()").fetchone()[0]
        if database != DEMO_DATABASE:
            sys.exit(f"Проверка выполняется только на демонстрационной базе «{DEMO_DATABASE}», а подключение к "
                     f"«{database}». Задайте: $env:PGDATABASE = \"{DEMO_DATABASE}\"")
        loaded = conn.execute("select count(*) from job_processes").fetchone()[0]
        if loaded != len(specs):
            sys.exit(f"В базе {loaded} процессов, а ожидается {len(specs)}. Загрузите демо-данные командой "
                     f"python -m db.seed.load_demo_data --today {today.isoformat()}")
        print(f"Сверка запросов с расчётом на Python: база {database}, дата {today:%d.%m.%Y}")
        run_checks(conn, specs, today)

    failed = [label for label, ok in results if not ok]
    print(f"\nИтого: проверок {len(results)}, успешно {len(results) - len(failed)}, ошибок {len(failed)}")
    if failed:
        print("Не пройдено:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)
    print("Все запросы совпали с независимым расчётом.")


if __name__ == "__main__":
    main()