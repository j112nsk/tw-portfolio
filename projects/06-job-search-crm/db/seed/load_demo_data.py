"""Загрузка демонстрационных данных в демонстрационную базу (US-19).

Запуск из корня проекта при активном виртуальном окружении. Имя базы задаётся в этом же
терминале (файл .env остаётся нетронутым):
    $env:PGDATABASE = "job_search_crm_demo"
    python -m db.seed.load_demo_data

Скрипт НЕ работает с другими базами: перед загрузкой он очищает данные процессов и навыков
(справочники остаются), поэтому по ошибке запущенный на рабочей базе он нанёс бы ущерб.
Данные синтетические: вымышленные компании (с пометкой «демо»), ссылки на example.com.
Даты считаются относительно дня запуска, поэтому напоминания всегда «живые».
Повторный запуск приводит демонстрационную базу к тому же состоянию без дублей.
"""
import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from db.connection import get_connection

DEMO_DATABASE = "job_search_crm_demo"
SEED = 20261011          # фиксированное начальное значение: набор данных воспроизводим
REGULAR_COUNT = 82       # обычные процессы; к ним добавляются «закреплённые» (см. pinned_specs)
PINNED_COUNT = 14        # число закреплённых процессов в pinned_specs
TW_SHARE = 0.30          # доля технических писателей среди всех процессов (остальное: SA/BA)

STAGES = ("APPLIED", "HR_INTERVIEW", "TECH_INTERVIEW", "TEAM_MEETING", "SECURITY_CHECK", "OFFER")
FUNNEL_STAGES = STAGES[1:]
OUTCOMES = ("OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME", "NO_RESPONSE")
REJECTIONS = ("REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME")
ALL_STATUSES = STAGES + OUTCOMES

DIRECTIONS = ("SA_BA", "TW")
SOURCES = ("HH_RU", "TELEGRAM_CHANNEL", "COMPANY_SITE", "OTHER")
APPLY_CHANNELS = ("HH_RU", "TELEGRAM", "EMAIL")
COMM_CHANNELS = ("HH_RU", "TELEGRAM", "EMAIL", "PHONE")
EMPLOYER_TYPES = ("DIRECT", "OUTSTAFF", "STAFFING_AGENCY")
EMPLOYMENT_FORMATS = ("LABOR_CONTRACT", "CIVIL_CONTRACT")
REASONS = ("NO_REASON", "EXPERIENCE_MISMATCH", "OTHER_CANDIDATE_CHOSEN", "CONDITIONS_MISMATCH", "OTHER")

PREFIXES = ["Нова", "Тера", "Ориент", "Вектор", "Лидер", "Гамма", "Сигма", "Альта",
            "Север", "Линия", "Мета", "Прима", "Вега", "Орбита", "Кварц"]
SUFFIXES = ["Софт", "Системы", "Технологии", "Дата", "Групп", "Лаб", "Сервис", "Проект"]

TITLES = {
    "SA_BA": ["Системный аналитик", "Бизнес-аналитик", "Аналитик", "Старший системный аналитик",
              "Системный аналитик (интеграции)", "Fullstack-аналитик"],
    "TW": ["Технический писатель", "Ведущий технический писатель", "Технический писатель (API)",
           "Senior Technical Writer", "Автор технической документации"],
}

SKILL_POOLS = {
    "SA_BA": ["SQL", "BPMN", "UML", "REST API", "SOAP", "Jira", "Confluence", "Postman",
              "Swagger/OpenAPI", "XML", "JSON", "Kafka", "RabbitMQ", "Use Case", "User Story",
              "Draw.io", "Figma", "Git", "Agile", "Scrum", "ER-диаграммы", "Анализ требований",
              "Интеграции", "Микросервисы", "PostgreSQL", "Python", "ЭДО", "Sequence-диаграммы",
              "Нефункциональные требования", "Тестирование"],
    "TW": ["Markdown", "Git", "Docs-as-Code", "DITA", "OpenAPI", "Confluence",
           "Технический английский", "Figma", "Sphinx", "MkDocs", "Postman", "Draw.io",
           "Руководство пользователя", "SQL", "XML", "Jira", "CI/CD", "API-документация",
           "Стайлгайд", "UML"],
}
# Профиль навыков соискателя: часть навыков из пулов выше намеренно в него не входит (пробелы)
PROFILE_SKILLS = {
    "SA_BA": ["SQL", "BPMN", "UML", "REST API", "Jira", "Confluence", "Postman", "Swagger/OpenAPI",
              "XML", "JSON", "Use Case", "User Story", "Draw.io", "Figma", "Git", "ЭДО",
              "Интеграции", "Анализ требований", "Нефункциональные требования"],
    "TW": ["Markdown", "Git", "Confluence", "Postman", "Draw.io", "Figma", "API-документация",
           "Руководство пользователя", "SQL", "XML", "Jira", "Стайлгайд"],
}

FIRST_NAMES = ["Анна", "Мария", "Ольга", "Елена", "Дмитрий", "Иван", "Сергей", "Алексей",
               "Наталья", "Ирина"]
SURNAME_INITIALS = "АБВГДЕЖЗКЛМНПРСТ"
CONTACT_POSITIONS = ["HR-менеджер", "Рекрутёр", "Руководитель отдела", "Руководитель проекта", "Тимлид"]
NOTES = ["Демо-комментарий: уточнить состав команды", "Демо-комментарий: обсудить формат работы",
         "Демо-комментарий: запросить детали по стеку"]

STAGE_GAPS = {"TECH_INTERVIEW": (4, 12), "TEAM_MEETING": (3, 9), "SECURITY_CHECK": (3, 8), "OFFER": (4, 10)}


# ---------------------------------------------------------------- структуры данных

@dataclass
class HistoryRec:
    status: str
    stage_date: date
    reason: str | None = None
    note: str | None = None


@dataclass
class TestSpec:
    status: str                    # статус, действовавший при получении задания
    received_on: date
    due_on: date | None
    submitted_on: date | None
    result_note: str | None = None


@dataclass
class ProcessSpec:
    direction: str
    initiator: str
    company: str
    title: str
    url: str | None
    source: str | None
    apply_channel: str | None
    comm_channel: str
    employer_type: str | None
    employment_format: str | None
    salary_from: int | None
    salary_to: int | None
    contact_name: str | None
    contact_position: str | None
    note: str | None
    history: list[HistoryRec] = field(default_factory=list)
    tests: list[TestSpec] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- генерация

def weighted(rng: random.Random, options: list[tuple[str, int]]) -> str:
    values, weights = zip(*options)
    return rng.choices(values, weights)[0]


def make_companies(rng: random.Random, count: int) -> list[str]:
    names = [f"{prefix}{suffix} (демо)" for prefix in PREFIXES for suffix in SUFFIXES]
    rng.shuffle(names)
    if count > len(names):
        raise ValueError("Не хватает названий компаний")
    return names[:count]


def make_salary(rng: random.Random, direction: str) -> tuple[int | None, int | None]:
    if rng.random() > 0.45:
        return None, None
    low, high = (140, 260) if direction == "SA_BA" else (100, 200)
    base = rng.randrange(low, high, 5) * 1000
    kind = rng.random()
    if kind < 0.6:
        return base, base + rng.randrange(20, 80, 10) * 1000
    if kind < 0.8:
        return base, None
    return None, base


def base_spec(rng: random.Random, company: str, direction: str | None = None,
              initiator: str | None = None) -> ProcessSpec:
    """Процесс со случайными атрибутами, без истории."""
    direction = direction or weighted(rng, [("SA_BA", 70), ("TW", 30)])
    initiator = initiator or weighted(rng, [("applicant", 78), ("employer", 22)])
    if initiator == "applicant":
        source = weighted(rng, [("HH_RU", 70), ("TELEGRAM_CHANNEL", 15), ("COMPANY_SITE", 10), ("OTHER", 5)])
        apply_channel = weighted(rng, [("HH_RU", 75), ("TELEGRAM", 15), ("EMAIL", 10)])
        comm_channel = weighted(rng, [("HH_RU", 30), ("TELEGRAM", 45), ("EMAIL", 15), ("PHONE", 10)])
    else:
        source = None
        apply_channel = None
        comm_channel = weighted(rng, [("TELEGRAM", 60), ("HH_RU", 20), ("EMAIL", 10), ("PHONE", 10)])
    salary_from, salary_to = make_salary(rng, direction)
    has_contact = rng.random() < 0.6
    return ProcessSpec(
        direction=direction,
        initiator=initiator,
        company=company,
        title=rng.choice(TITLES[direction]),
        url=f"https://example.com/vacancy/{rng.randint(100000, 999999)}" if rng.random() < 0.7 else None,
        source=source,
        apply_channel=apply_channel,
        comm_channel=comm_channel,
        employer_type=(weighted(rng, [("DIRECT", 60), ("OUTSTAFF", 20), ("STAFFING_AGENCY", 20)])
                       if rng.random() < 0.7 else None),
        employment_format=(weighted(rng, [("LABOR_CONTRACT", 80), ("CIVIL_CONTRACT", 20)])
                           if rng.random() < 0.6 else None),
        salary_from=salary_from,
        salary_to=salary_to,
        contact_name=f"{rng.choice(FIRST_NAMES)} {rng.choice(SURNAME_INITIALS)}." if has_contact else None,
        contact_position=rng.choice(CONTACT_POSITIONS) if has_contact else None,
        note=rng.choice(NOTES) if rng.random() < 0.25 else None,
    )


def pick_outcome(rng: random.Random, last_status: str) -> str:
    if last_status == "OFFER":
        return weighted(rng, [("OFFER_ACCEPTED", 35), ("OFFER_DECLINED", 40),
                              ("REJECTED_BY_EMPLOYER", 10), ("NO_RESPONSE", 15)])
    return weighted(rng, [("REJECTED_BY_EMPLOYER", 55), ("WITHDRAWN_BY_ME", 15), ("NO_RESPONSE", 30)])


def pick_reason(rng: random.Random, outcome: str) -> str | None:
    if outcome == "REJECTED_BY_EMPLOYER":
        return weighted(rng, [("NO_REASON", 25), ("EXPERIENCE_MISMATCH", 25), ("OTHER_CANDIDATE_CHOSEN", 30),
                              ("CONDITIONS_MISMATCH", 5), ("OTHER", 15)])
    if outcome == "WITHDRAWN_BY_ME":
        return weighted(rng, [("CONDITIONS_MISMATCH", 50), ("OTHER", 25), ("NO_REASON", 25)])
    return None


def assign_skills(rng: random.Random, spec: ProcessSpec, probability: float) -> None:
    """Навыки вводятся только у процессов, дошедших до HR-интервью и далее (D8)."""
    reached = any(rec.status in FUNNEL_STAGES for rec in spec.history)
    if reached and rng.random() < probability:
        spec.skills = rng.sample(SKILL_POOLS[spec.direction], rng.randint(3, 7))


def build_timeline(rng: random.Random, today: date, spec: ProcessSpec) -> None:
    """Строит историю и тестовые задания обычного процесса."""
    start = today - timedelta(days=rng.randint(0, 270))
    test_first = spec.initiator == "applicant" and rng.random() < 0.10
    history: list[HistoryRec] = []
    tests: list[TestSpec] = []
    d = start
    go_on = True

    if test_first:
        due = d + timedelta(days=rng.randint(4, 8))
        submitted = max(d, due - timedelta(days=rng.randint(0, 2))) if due <= today else None
        history.append(HistoryRec("APPLIED", d, note="Выдано тестовое задание"))
        tests.append(TestSpec("APPLIED", d, due, submitted,
                              "Задание сдано, ждём обратную связь" if submitted else None))
        d = (submitted or due) + timedelta(days=rng.randint(2, 7))
        go_on = rng.random() < 0.7

    path: list[str] = []
    if go_on:
        path = ["HR_INTERVIEW"]
        if rng.random() < 0.6:
            path.append("TECH_INTERVIEW")
            if rng.random() < 0.35:
                path.append("TEAM_MEETING")
            if rng.random() < 0.30:
                path.append("SECURITY_CHECK")
            if rng.random() < 0.55:
                path.append("OFFER")

    scheduled_future = False
    for index, status in enumerate(path):
        if index > 0:
            low, high = STAGE_GAPS[status]
            d = d + timedelta(days=rng.randint(low, high))
        history.append(HistoryRec(status, d))
        if d > today:             # будущий этап: дальше события ещё неизвестны
            scheduled_future = True
            break

    reached_tech = any(rec.status == "TECH_INTERVIEW" for rec in history)
    if reached_tech and rng.random() < 0.30:
        hr_date = next(rec.stage_date for rec in history if rec.status == "HR_INTERVIEW")
        received = hr_date + timedelta(days=rng.randint(1, 3))
        if received <= today:
            due = received + timedelta(days=rng.randint(3, 7))
            submitted = max(received, due - timedelta(days=rng.randint(0, 2))) if due <= today else None
            tests.append(TestSpec("HR_INTERVIEW", received, due, submitted,
                                  "Задание сдано, ждём обратную связь" if submitted else None))

    has_future_test = any(t.submitted_on is None and t.due_on is not None and t.due_on >= today for t in tests)
    if not scheduled_future and not has_future_test:
        last = history[-1]
        anchor = max([last.stage_date] + [t.submitted_on or t.due_on for t in tests
                                          if (t.submitted_on or t.due_on) is not None])
        close_date = anchor + timedelta(days=rng.randint(1, 9))
        if close_date <= today and rng.random() < 0.88:
            outcome = pick_outcome(rng, last.status)
            history.append(HistoryRec(outcome, close_date, pick_reason(rng, outcome)))

    spec.history = history
    spec.tests = tests
    assign_skills(rng, spec, 0.7)


def pinned_specs(rng: random.Random, today: date, companies) -> list[ProcessSpec]:
    """Процессы с заданными датами: гарантируют, что на странице напоминаний есть все три группы,
    а в справочнике статусов использован каждый статус."""
    def day(offset: int) -> date:
        return today + timedelta(days=offset)

    def make(direction: str, initiator: str, history: list[HistoryRec],
             tests: list[TestSpec] | None = None) -> ProcessSpec:
        spec = base_spec(rng, next(companies), direction, initiator)
        spec.history = history
        spec.tests = tests or []
        assign_skills(rng, spec, 1.0)
        return spec

    hr, tech, team, sec, offer = ("HR_INTERVIEW", "TECH_INTERVIEW", "TEAM_MEETING",
                                  "SECURITY_CHECK", "OFFER")
    return [
        # «Сегодня и завтра»
        make("SA_BA", "applicant", [HistoryRec(hr, day(0))]),
        make("SA_BA", "applicant", [HistoryRec(hr, day(-8)), HistoryRec(tech, day(1))]),
        make("TW", "employer", [HistoryRec(hr, day(1))]),
        # «В ближайшие 7 дней»
        make("TW", "applicant", [HistoryRec(hr, day(3))]),
        make("SA_BA", "applicant", [HistoryRec(hr, day(-5)), HistoryRec(tech, day(6))]),
        make("SA_BA", "applicant", [HistoryRec(hr, day(-6))],
             [TestSpec(hr, day(-2), day(4), None)]),                       # срок сдачи тестового
        make("SA_BA", "applicant", [HistoryRec(hr, day(-25)), HistoryRec(tech, day(-15)),
                                    HistoryRec(offer, day(5))]),           # срок ответа на оффер
        make("SA_BA", "applicant", [HistoryRec(hr, day(-30)), HistoryRec(tech, day(-20)),
                                    HistoryRec(team, day(4))]),
        # «Нет запланированного этапа»
        make("SA_BA", "applicant", [HistoryRec(hr, day(-12))]),
        make("TW", "applicant", [HistoryRec(hr, day(-20)), HistoryRec(tech, day(-9))]),
        make("SA_BA", "employer", [HistoryRec(hr, day(-15))]),
        make("SA_BA", "applicant", [HistoryRec("APPLIED", day(-10), note="Выдано тестовое задание")],
             [TestSpec("APPLIED", day(-10), day(-3), None)]),             # просроченное несданное тестовое
        make("SA_BA", "applicant", [HistoryRec(hr, day(-28)), HistoryRec(tech, day(-18)),
                                    HistoryRec(team, day(-10)), HistoryRec(sec, day(-2))]),
        # процесс, возвращённый в работу после отказа (в Q8 не входит, UQ4)
        make("TW", "applicant", [HistoryRec(hr, day(-30)),
                                 HistoryRec("REJECTED_BY_EMPLOYER", day(-25), reason="OTHER_CANDIDATE_CHOSEN"),
                                 HistoryRec(tech, day(2))]),
    ]


def reminder_groups(spec: ProcessSpec, today: date) -> set[str]:
    """Группы напоминаний процесса по правилу SR13: soon, week, none."""
    if spec.history[-1].status not in STAGES:
        return set()
    dates = [rec.stage_date for rec in spec.history if rec.status in STAGES and rec.stage_date >= today]
    dates += [t.due_on for t in spec.tests
              if t.submitted_on is None and t.due_on is not None and t.due_on >= today]
    if not dates:
        return {"none"}
    groups = set()
    for d in dates:
        if d <= today + timedelta(days=1):
            groups.add("soon")
        elif d <= today + timedelta(days=7):
            groups.add("week")
    return groups


def ensure_coverage(rng: random.Random, specs: list[ProcessSpec]) -> None:
    """Подменяет значения так, чтобы каждое значение справочников встретилось хотя бы раз."""
    applicants = [s for s in specs if s.initiator == "applicant"]
    dimensions = [
        (DIRECTIONS, specs, "direction"),
        (SOURCES, applicants, "source"),
        (APPLY_CHANNELS, applicants, "apply_channel"),
        (COMM_CHANNELS, specs, "comm_channel"),
        (EMPLOYER_TYPES, [s for s in specs if s.employer_type], "employer_type"),
        (EMPLOYMENT_FORMATS, [s for s in specs if s.employment_format], "employment_format"),
    ]
    for _ in range(5):
        changed = False
        for values, pool, attribute in dimensions:
            present = {getattr(s, attribute) for s in pool}
            for value in values:
                if value not in present:
                    setattr(rng.choice(pool), attribute, value)
                    present = {getattr(s, attribute) for s in pool}
                    changed = True
        records = [rec for s in specs for rec in s.history if rec.status in REJECTIONS]
        used = {rec.reason for rec in records}
        for value in REASONS:
            if value not in used:
                rng.choice(records).reason = value
                used = {rec.reason for rec in records}
                changed = True
        if not changed:
            break


def validate(specs: list[ProcessSpec], today: date) -> list[str]:
    """Возвращает список нарушений требований US-19 и правил целостности; пустой = всё хорошо."""
    problems: list[str] = []

    def need(condition: bool, text: str) -> None:
        if not condition:
            problems.append(text)

    need(len(specs) >= 80, f"процессов меньше 80: {len(specs)}")
    tw_share = sum(1 for s in specs if s.direction == "TW") / len(specs)
    need(abs(tw_share - TW_SHARE) <= 0.01, f"доля TW {tw_share:.1%} отличается от {TW_SHARE:.0%}")
    need(len({s.company for s in specs}) == len(specs), "названия компаний повторяются")
    for values, getter, label in [
        (DIRECTIONS, lambda s: s.direction, "направление"),
        (("applicant", "employer"), lambda s: s.initiator, "инициатор"),
        (SOURCES, lambda s: s.source, "источник вакансии"),
        (APPLY_CHANNELS, lambda s: s.apply_channel, "канал отклика"),
        (COMM_CHANNELS, lambda s: s.comm_channel, "канал общения"),
        (EMPLOYER_TYPES, lambda s: s.employer_type, "тип работодателя"),
        (EMPLOYMENT_FORMATS, lambda s: s.employment_format, "формат трудоустройства"),
    ]:
        present = {getter(s) for s in specs}
        for value in values:
            need(value in present, f"не использовано значение «{value}» ({label})")
    reasons = {rec.reason for s in specs for rec in s.history if rec.status in REJECTIONS}
    for value in REASONS:
        need(value in reasons, f"не использована причина отказа «{value}»")
    current = {s.history[-1].status for s in specs}
    for status in ALL_STATUSES:
        need(status in current, f"нет процессов с текущим статусом «{status}»")

    need(sum(len(s.tests) for s in specs) >= 10, "тестовых заданий меньше 10")
    need(sum(1 for s in specs if s.skills) >= 30, "процессов с навыками меньше 30")
    need(sum(1 for s in specs if s.salary_from or s.salary_to) >= 20, "процессов с вилкой меньше 20")

    groups = [reminder_groups(s, today) for s in specs]
    for group in ("soon", "week", "none"):
        need(sum(1 for g in groups if group in g) >= 3, f"в группе напоминаний «{group}» меньше 3 записей")

    for s in specs:
        name = s.company
        need(bool(s.history), f"{name}: нет истории")
        if not s.history:
            continue
        need(s.history[0].status in STAGES, f"{name}: первая запись не этап (INV-09)")
        need(all(a.stage_date <= b.stage_date for a, b in zip(s.history, s.history[1:])),
             f"{name}: даты истории не по возрастанию")
        if s.history[0].status == "APPLIED":
            need(bool(s.tests), f"{name}: начат с «Отклика» без тестового (INV-20)")
        last = s.history[-1]
        qualifies = any(rec.status in FUNNEL_STAGES for rec in s.history) or bool(s.tests)
        if last.status in REJECTIONS and qualifies:
            need(last.reason is not None, f"{name}: отказ без причины (INV-08)")
        for rec in s.history:
            if rec.reason is not None:
                need(rec.status in REJECTIONS, f"{name}: причина у записи не об отказе")
        if s.initiator == "employer":
            need(s.source is None and s.apply_channel is None, f"{name}: у входящего заполнены источник/канал отклика")
        else:
            need(s.source is not None and s.apply_channel is not None, f"{name}: у отклика нет источника/канала отклика")
        need(not (s.salary_from and s.salary_to and s.salary_from > s.salary_to), f"{name}: вилка «от» больше «до»")
        for t in s.tests:
            need(t.due_on is None or t.due_on >= t.received_on, f"{name}: срок сдачи раньше получения")
            need(t.submitted_on is None or t.submitted_on >= t.received_on, f"{name}: сдача раньше получения")
        if s.skills:
            need(any(rec.status in FUNNEL_STAGES for rec in s.history), f"{name}: навыки без HR-интервью (D8)")
    return problems


def generate_demo(today: date, seed: int = SEED) -> list[ProcessSpec]:
    rng = random.Random(seed)
    companies = iter(make_companies(rng, REGULAR_COUNT + PINNED_COUNT))
    pinned = pinned_specs(rng, today, companies)
    if len(pinned) != PINNED_COUNT:
        raise RuntimeError(f"Ожидалось {PINNED_COUNT} закреплённых процессов, получено {len(pinned)}")

    # Направления распределяются точно: TW_SHARE от всех процессов, остальное SA/BA
    total = REGULAR_COUNT + PINNED_COUNT
    regular_tw = round(TW_SHARE * total) - sum(1 for s in pinned if s.direction == "TW")
    directions = ["TW"] * regular_tw + ["SA_BA"] * (REGULAR_COUNT - regular_tw)
    rng.shuffle(directions)

    specs = []
    for direction in directions:
        spec = base_spec(rng, next(companies), direction=direction)
        build_timeline(rng, today, spec)
        specs.append(spec)
    specs.extend(pinned)
    ensure_coverage(rng, specs)
    problems = validate(specs, today)
    if problems:
        raise RuntimeError("Демонстрационные данные не прошли проверку:\n  " + "\n  ".join(problems))
    return specs


# ---------------------------------------------------------------- загрузка в базу

INSERT_PROCESS = """
insert into job_processes
    (direction_id, initiator, company_name, vacancy_title, vacancy_url,
     vacancy_source_id, apply_channel_id, communication_channel_id,
     employer_type_id, employment_format_id, salary_from, salary_to,
     contact_name, contact_position, note, status_id)
values
    ((select id from directions where code = %(direction)s), %(initiator)s, %(company)s, %(title)s, %(url)s,
     (select id from vacancy_sources where code = %(source)s),
     (select id from channels where code = %(apply_channel)s),
     (select id from channels where code = %(comm_channel)s),
     (select id from employer_types where code = %(employer_type)s),
     (select id from employment_formats where code = %(employment_format)s),
     %(salary_from)s, %(salary_to)s, %(contact_name)s, %(contact_position)s, %(note)s,
     (select id from statuses where code = %(status)s))
returning id
"""

INSERT_HISTORY = """
insert into process_status_history
    (process_id, status_id, stage_date, recorded_at, note, rejection_reason_id)
values
    (%(process_id)s, (select id from statuses where code = %(status)s), %(stage_date)s, %(recorded_at)s,
     %(note)s, (select id from rejection_reasons where code = %(reason)s))
"""

INSERT_TEST = """
insert into test_assignments (process_id, status_id, received_on, due_on, submitted_on, result_note)
values (%(process_id)s, (select id from statuses where code = %(status)s), %(received_on)s,
        %(due_on)s, %(submitted_on)s, %(result_note)s)
"""


def recorded_times(rng: random.Random, today: date, history: list[HistoryRec]) -> list[datetime]:
    """Моменты создания записей: по возрастанию, не позже дня этапа (для будущих этапов — не позже сегодня)."""
    result: list[datetime] = []
    for rec in history:
        anchor = min(rec.stage_date, today)
        moment = datetime.combine(anchor, time(10, 0)).astimezone() - timedelta(days=rng.randint(0, 2))
        if result and moment <= result[-1]:
            moment = result[-1] + timedelta(minutes=1)
        result.append(moment)
    return result


def load(conn, specs: list[ProcessSpec], today: date) -> None:
    rng = random.Random(SEED + 1)
    conn.execute("truncate table process_skills, profile_skills, test_assignments, "
                 "process_status_history, job_processes, skills restart identity")

    skill_names = sorted({name for pool in SKILL_POOLS.values() for name in pool}
                         | {name for pool in PROFILE_SKILLS.values() for name in pool})
    for name in skill_names:
        conn.execute("insert into skills (name) values (%s) on conflict do nothing", (name,))
    for direction, names in PROFILE_SKILLS.items():
        for name in names:
            conn.execute("""insert into profile_skills (direction_id, skill_id)
                            select d.id, s.id from directions d, skills s
                             where d.code = %s and lower(s.name) = lower(%s)""", (direction, name))

    for spec in specs:
        process_id = conn.execute(INSERT_PROCESS, {
            "direction": spec.direction, "initiator": spec.initiator, "company": spec.company,
            "title": spec.title, "url": spec.url, "source": spec.source,
            "apply_channel": spec.apply_channel, "comm_channel": spec.comm_channel,
            "employer_type": spec.employer_type, "employment_format": spec.employment_format,
            "salary_from": spec.salary_from, "salary_to": spec.salary_to,
            "contact_name": spec.contact_name, "contact_position": spec.contact_position,
            "note": spec.note, "status": spec.history[0].status,
        }).fetchone()[0]
        for rec, moment in zip(spec.history, recorded_times(rng, today, spec.history)):
            conn.execute(INSERT_HISTORY, {
                "process_id": process_id, "status": rec.status, "stage_date": rec.stage_date,
                "recorded_at": moment, "note": rec.note, "reason": rec.reason})
        for test in spec.tests:
            conn.execute(INSERT_TEST, {
                "process_id": process_id, "status": test.status, "received_on": test.received_on,
                "due_on": test.due_on, "submitted_on": test.submitted_on, "result_note": test.result_note})
        for name in spec.skills:
            conn.execute("""insert into process_skills (process_id, skill_id)
                            select %s, id from skills where lower(name) = lower(%s)""", (process_id, name))


def print_summary(conn) -> None:
    count = lambda table: conn.execute(f"select count(*) from {table}").fetchone()[0]
    print(f"Загружено: процессов {count('job_processes')}, записей истории {count('process_status_history')}, "
          f"тестовых заданий {count('test_assignments')}, навыков {count('skills')}, "
          f"связей процесс-навык {count('process_skills')}, навыков в профиле {count('profile_skills')}.")
    print("Процессы по текущему статусу:")
    for name, number in conn.execute("""
            select s.name_ru, count(*) from job_processes p join statuses s on s.id = p.status_id
             group by s.name_ru, s.sort_order order by s.sort_order"""):
        print(f"  {name:28} {number}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка демонстрационных данных")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(),
                        help="«сегодняшняя» дата для расчёта дат демо-данных, ГГГГ-ММ-ДД (по умолчанию сегодня)")
    today = parser.parse_args().today
    specs = generate_demo(today)           # проверка требований US-19 выполняется внутри
    with get_connection() as conn:
        database = conn.execute("select current_database()").fetchone()[0]
        if database != DEMO_DATABASE:
            sys.exit(f"Отказ: загрузка разрешена только в базу «{DEMO_DATABASE}», а подключение к «{database}».\n"
                     f"Задайте имя базы в этом терминале: $env:PGDATABASE = \"{DEMO_DATABASE}\"")
        conn.commit()
        with conn.transaction():
            load(conn, specs, today)
        conn.commit()
        print(f"База: {database}; дата загрузки: {today:%d.%m.%Y} (параметр --today {today.isoformat()})")
        print_summary(conn)


if __name__ == "__main__":
    main()
