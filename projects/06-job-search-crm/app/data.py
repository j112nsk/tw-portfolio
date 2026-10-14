"""Слой данных приложения: только чтение, без Streamlit.

Правила:
  * соединение — psycopg 3, обычный SQL, без ORM (см. db/connection.py);
  * строки возвращаются словарями (dict_row);
  * фильтры передаются именованными параметрами, каждый — с явным приведением типа;
  * значения справочников сравниваются по code (PM-03), а не по id;
  * приложение не кэширует данные: соединение открывается на время вызова и закрывается
    (в будущем при записи это гарантирует свежие данные без инвалидации).
"""
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from db.connection import get_connection
from db.run_queries import run_file

QUERIES_DIR = Path(__file__).resolve().parent.parent / "db" / "queries"

# Справочники, которые можно запросить целиком (белый список).
REFERENCE_TABLES = {
    "directions",
    "vacancy_sources",
    "channels",
    "employer_types",
    "employment_formats",
    "rejection_reasons",
    "statuses",
}


# ---------------------------------------------------------------- соединение

def _fetch_all(sql: str, params: dict | None = None,
               conn: psycopg.Connection | None = None) -> list[dict]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()
    finally:
        if own:
            conn.close()


def _fetch_one(sql: str, params: dict | None = None,
               conn: psycopg.Connection | None = None) -> dict | None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchone()
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------- база и справочники

def database_info() -> dict:
    """Имя текущей базы и признак демонстрационного режима."""
    conn = get_connection()
    try:
        name = conn.execute("select current_database()").fetchone()[0]
    finally:
        conn.close()
    return {"name": name, "is_demo": name.endswith("_demo")}


def get_reference(name: str) -> list[dict]:
    """Значения справочника в порядке вывода: id, code, name_ru."""
    if name not in REFERENCE_TABLES:
        raise ValueError(f"Неизвестный справочник: {name}")
    sql = f"select id, code, name_ru from {name} order by sort_order"
    return _fetch_all(sql)


def get_apply_channels() -> list[dict]:
    """Каналы, которыми можно откликнуться (is_apply_channel = true)."""
    return _fetch_all(
        "select id, code, name_ru from channels where is_apply_channel order by sort_order"
    )


def count_processes() -> int:
    conn = get_connection()
    try:
        return conn.execute("select count(*) from job_processes").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- список процессов

LIST_PROCESSES_SQL = """
with last_history as (
    select distinct on (h.process_id)
           h.process_id,
           h.stage_date as last_record_date
      from process_status_history h
     order by h.process_id, h.stage_date desc, h.recorded_at desc, h.id desc
),
start_date as (
    select h.process_id, min(h.stage_date) as start_date
      from process_status_history h
      join statuses s on s.id = h.status_id and s.kind = 'stage'
     group by h.process_id
),
next_stage as (
    select distinct on (h.process_id)
           h.process_id,
           h.stage_date as next_date,
           s.name_ru    as next_name
      from process_status_history h
      join statuses s on s.id = h.status_id
     where s.kind = 'stage'
       and h.stage_date >= %(today)s::date
     order by h.process_id, h.stage_date asc, h.id asc
)
select p.id,
       p.company_name,
       p.vacancy_title,
       p.vacancy_url,
       p.initiator,
       d.code     as direction_code,
       d.name_ru  as direction,
       st.name_ru as status_name,
       st.kind    as status_kind,
       lh.last_record_date,
       sd.start_date,
       case when st.kind = 'stage' then ns.next_date end as next_date,
       case when st.kind = 'stage' then ns.next_name end as next_name
  from job_processes p
  join directions d  on d.id  = p.direction_id
  join statuses   st on st.id = p.status_id
  left join vacancy_sources vs on vs.id = p.vacancy_source_id
  left join channels       ac on ac.id = p.apply_channel_id
  left join channels       cc on cc.id = p.communication_channel_id
  left join employer_types et on et.id = p.employer_type_id
  left join employment_formats ef on ef.id = p.employment_format_id
  left join last_history lh on lh.process_id = p.id
  left join start_date   sd on sd.process_id = p.id
  left join next_stage   ns on ns.process_id = p.id
 where (%(state)s::text is null
        or (%(state)s = 'open'   and st.kind = 'stage')
        or (%(state)s = 'closed' and st.kind = 'outcome'))
   and (cardinality(%(directions)s::text[]) = 0
        or d.code = any(%(directions)s::text[]))
   and (cardinality(%(statuses)s::text[]) = 0
        or st.code = any(%(statuses)s::text[]))
   and (%(initiator)s::text         is null or p.initiator = %(initiator)s)
   and (%(source)s::text            is null or vs.code = %(source)s)
   and (%(apply_channel)s::text     is null or ac.code = %(apply_channel)s)
   and (%(comm_channel)s::text      is null or cc.code = %(comm_channel)s)
   and (%(employer_type)s::text     is null or et.code = %(employer_type)s)
   and (%(employment_format)s::text is null or ef.code = %(employment_format)s)
   and (%(date_from)s::date is null or sd.start_date >= %(date_from)s)
   and (%(date_to)s::date   is null or sd.start_date <= %(date_to)s)
   and (%(search)s::text is null
        or strpos(lower(p.company_name),  lower(%(search)s)) > 0
        or strpos(lower(p.vacancy_title), lower(%(search)s)) > 0
        or strpos(lower(coalesce(p.vacancy_url, '')), lower(%(search)s)) > 0)
 order by lh.last_record_date desc nulls last, p.id desc
 limit 1000
"""


def list_processes(filters: dict | None, today: date) -> list[dict]:
    """Список процессов с фильтрами (US-02, US-03). None = без фильтра.

    Поиск по подстроке (strpos), поэтому символы % и _ не являются шаблонами
    (US-03, критерий «служебные символы не должны находить всё подряд»).
    """
    f = filters or {}
    search = (f.get("search") or "").strip() or None
    params = {
        "today": today,
        "state": f.get("state") or None,
        "directions": [c for c in (f.get("directions") or []) if c],
        "statuses":   [c for c in (f.get("statuses")   or []) if c],
        "initiator": f.get("initiator") or None,
        "source": f.get("source") or None,
        "apply_channel": f.get("apply_channel") or None,
        "comm_channel": f.get("comm_channel") or None,
        "employer_type": f.get("employer_type") or None,
        "employment_format": f.get("employment_format") or None,
        "date_from": f.get("date_from") or None,
        "date_to": f.get("date_to") or None,
        "search": search,
    }
    return _fetch_all(LIST_PROCESSES_SQL, params)


# ---------------------------------------------------------------- напоминания

def get_reminders(today: date) -> list[dict]:
    """Три группы напоминаний (US-08, US-09, Q4): готовый SQL db/queries/01-reminders.sql."""
    conn = get_connection()
    try:
        columns, rows = run_file(conn, QUERIES_DIR / "01-reminders.sql", {"today": today})
    finally:
        conn.close()
    return [dict(zip(columns, row)) for row in rows]


# ---------------------------------------------------------------- карточка процесса

CARD_PROCESS_SQL = """
select p.id,
       p.company_name,
       p.vacancy_title,
       p.vacancy_url,
       p.initiator,
       p.salary_from,
       p.salary_to,
       p.contact_name,
       p.contact_position,
       p.note,
       d.name_ru  as direction,
       st.name_ru as status,
       st.kind    as status_kind,
       vs.name_ru as source,
       ac.name_ru as apply_channel,
       cc.name_ru as comm_channel,
       et.name_ru as employer_type,
       ef.name_ru as employment_format
  from job_processes p
  join directions d  on d.id  = p.direction_id
  join statuses   st on st.id = p.status_id
  join channels   cc on cc.id = p.communication_channel_id
  left join vacancy_sources    vs on vs.id = p.vacancy_source_id
  left join channels           ac on ac.id = p.apply_channel_id
  left join employer_types     et on et.id = p.employer_type_id
  left join employment_formats ef on ef.id = p.employment_format_id
 where p.id = %(pid)s
"""

CARD_HISTORY_SQL = """
select h.id,
       h.stage_date,
       s.name_ru  as status,
       rr.name_ru as reason,
       h.note,
       h.recorded_at
  from process_status_history h
  join statuses s on s.id = h.status_id
  left join rejection_reasons rr on rr.id = h.rejection_reason_id
 where h.process_id = %(pid)s
 order by h.stage_date asc, h.recorded_at asc, h.id asc
"""

CARD_TESTS_SQL = """
select t.id,
       t.received_on,
       t.due_on,
       t.submitted_on,
       t.result_note,
       s.name_ru as status_at_receipt
  from test_assignments t
  join statuses s on s.id = t.status_id
 where t.process_id = %(pid)s
 order by t.received_on asc, t.id asc
"""

CARD_SKILLS_SQL = """
select sk.name
  from process_skills ps
  join skills sk on sk.id = ps.skill_id
 where ps.process_id = %(pid)s
 order by lower(sk.name)
"""


def get_process_card(process_id: int) -> dict | None:
    """Карточка процесса или None, если его нет."""
    process = _fetch_one(CARD_PROCESS_SQL, {"pid": process_id})
    if process is None:
        return None
    history = _fetch_all(CARD_HISTORY_SQL, {"pid": process_id})
    tests = _fetch_all(CARD_TESTS_SQL, {"pid": process_id})
    skills = [row["name"] for row in _fetch_all(CARD_SKILLS_SQL, {"pid": process_id})]
    return {"process": process, "history": history, "tests": tests, "skills": skills}

# ---------------------------------------------------------------- запись: создание процесса

CREATE_PROCESS_SQL = """
insert into job_processes
    (direction_id, initiator, company_name, vacancy_title, vacancy_url,
     vacancy_source_id, apply_channel_id, communication_channel_id,
     employer_type_id, employment_format_id, salary_from, salary_to,
     contact_name, contact_position, note, status_id)
values
    ((select id from directions          where code = %(direction_code)s),
     %(initiator)s, %(company_name)s, %(vacancy_title)s, %(vacancy_url)s,
     (select id from vacancy_sources     where code = %(vacancy_source_code)s),
     (select id from channels            where code = %(apply_channel_code)s),
     (select id from channels            where code = %(communication_channel_code)s),
     (select id from employer_types      where code = %(employer_type_code)s),
     (select id from employment_formats  where code = %(employment_format_code)s),
     %(salary_from)s, %(salary_to)s,
     %(contact_name)s, %(contact_position)s, %(note)s,
     (select id from statuses            where code = %(initial_status_code)s))
returning id
"""

INSERT_FIRST_HISTORY_SQL = """
insert into process_status_history (process_id, status_id, stage_date)
values (%(pid)s,
        (select id from statuses where code = %(status_code)s),
        %(stage_date)s)
"""

INSERT_FIRST_TEST_SQL = """
insert into test_assignments (process_id, status_id, received_on, due_on)
values (%(pid)s,
        (select id from statuses where code = %(status_code)s),
        %(received_on)s, %(due_on)s)
"""


def get_initial_stages() -> list[dict]:
    """Этапы для формы создания процесса (SR1: только kind = 'stage')."""
    return _fetch_all(
        "select id, code, name_ru, stage_order from statuses "
        "where kind = 'stage' order by stage_order"
    )


def get_last_process_defaults(conn: psycopg.Connection | None = None) -> dict:
    """Значения по умолчанию для формы (US-01, критерий 2).

    direction и communication_channel — из самого недавно созданного процесса (id desc);
    vacancy_source и apply_channel — из самого недавно созданного процесса с инициатором
    applicant (у входящих они пусты, D11).
    Если процессов нет — все значения None.

    Параметр conn позволяет вызывать функцию в чужой транзакции (тесты, составные операции).
    """
    last = _fetch_one("""
        select d.code as direction_code,
               cc.code as communication_channel_code
          from job_processes p
          join directions d  on d.id  = p.direction_id
          join channels   cc on cc.id = p.communication_channel_id
         order by p.id desc
         limit 1
    """, conn=conn) or {"direction_code": None, "communication_channel_code": None}

    last_applicant = _fetch_one("""
        select vs.code as vacancy_source_code,
               ac.code as apply_channel_code
          from job_processes p
          join vacancy_sources vs on vs.id = p.vacancy_source_id
          join channels       ac on ac.id = p.apply_channel_id
         where p.initiator = 'applicant'
         order by p.id desc
         limit 1
    """, conn=conn) or {"vacancy_source_code": None, "apply_channel_code": None}

    return {**last, **last_applicant}


_REFERENCE_TABLES = {
    "directions", "vacancy_sources", "channels", "employer_types",
    "employment_formats", "statuses", "rejection_reasons",
}


def _ensure_reference_codes(checks: list[tuple[str, str | None, str]],
                            conn: psycopg.Connection | None = None) -> None:
    """Проверяет, что справочные коды существуют.

    checks: список троек (таблица, код, метка для сообщения об ошибке).
    None пропускается. Если код задан, но не найден — ValueError.
    """
    for table, code, label in checks:
        if code is None:
            continue
        if table not in _REFERENCE_TABLES:
            raise ValueError(f"Внутренняя ошибка: неизвестный справочник {table}")
        row = _fetch_one(f"select 1 from {table} where code = %(code)s",
                         {"code": code}, conn=conn)
        if row is None:
            raise ValueError(f"{label}: значение «{code}» не найдено в справочнике.")


def _validate_common_fields(
    *,
    initiator: str,
    company_name: str,
    vacancy_title: str,
    vacancy_url: str | None,
    vacancy_source_code: str | None,
    apply_channel_code: str | None,
    communication_channel_code: str | None,
    salary_from: int | None,
    salary_to: int | None,
) -> None:
    """Валидации полей процесса, общие для создания и правки (US-01, US-05)."""
    if not company_name or not company_name.strip():
        raise ValueError("Укажите название компании.")
    if not vacancy_title or not vacancy_title.strip():
        raise ValueError("Укажите название вакансии.")
    if not communication_channel_code:
        raise ValueError("Канал общения обязателен (INV-03).")

    if initiator == "applicant":
        if not vacancy_source_code:
            raise ValueError("Для процесса, начатого откликом, укажите источник вакансии (INV-02).")
        if not apply_channel_code:
            raise ValueError("Для процесса, начатого откликом, укажите канал отклика (INV-02).")
    else:
        if vacancy_source_code or apply_channel_code:
            raise ValueError("У входящего процесса источник вакансии и канал отклика не заполняются (INV-02).")

    if vacancy_url:
        if not (vacancy_url.startswith("http://") or vacancy_url.startswith("https://")):
            raise ValueError("Ссылка на вакансию должна начинаться с http:// или https:// (INV-07).")
        if any(ch.isspace() for ch in vacancy_url):
            raise ValueError("Ссылка на вакансию не должна содержать пробелов (INV-07).")

    if salary_from is not None and salary_from <= 0:
        raise ValueError("Вилка «от» должна быть больше нуля (INV-05).")
    if salary_to is not None and salary_to <= 0:
        raise ValueError("Вилка «до» должна быть больше нуля (INV-05).")
    if salary_from is not None and salary_to is not None and salary_from > salary_to:
        raise ValueError("Вилка «от» не должна быть больше «до» (INV-05).")


def _validate_create_process(
    *,
    initiator: str,
    company_name: str,
    vacancy_title: str,
    vacancy_url: str | None,
    vacancy_source_code: str | None,
    apply_channel_code: str | None,
    communication_channel_code: str | None,
    salary_from: int | None,
    salary_to: int | None,
    initial_status_code: str,
    test_due_on: date | None,
) -> None:
    if initiator not in ("applicant", "employer"):
        raise ValueError("Инициатор должен быть applicant или employer (INV-01).")

    _validate_common_fields(
        initiator=initiator, company_name=company_name, vacancy_title=vacancy_title,
        vacancy_url=vacancy_url, vacancy_source_code=vacancy_source_code,
        apply_channel_code=apply_channel_code,
        communication_channel_code=communication_channel_code,
        salary_from=salary_from, salary_to=salary_to,
    )

    if initial_status_code != "APPLIED" and test_due_on is not None:
        raise ValueError("Срок сдачи тестового задания можно указать только "
                         "при начальном статусе «Отклик» (US-01, критерий 5).")


def create_process(
    *,
    direction_code: str,
    initiator: str,
    company_name: str,
    vacancy_title: str,
    initial_status_code: str,
    initial_stage_date: date,
    communication_channel_code: str,
    vacancy_source_code: str | None = None,
    apply_channel_code: str | None = None,
    vacancy_url: str | None = None,
    employer_type_code: str | None = None,
    employment_format_code: str | None = None,
    salary_from: int | None = None,
    salary_to: int | None = None,
    contact_name: str | None = None,
    contact_position: str | None = None,
    note: str | None = None,
    test_due_on: date | None = None,
    conn: psycopg.Connection | None = None,
) -> int:
    """Создаёт процесс (US-01): job_processes + первая запись истории (+ тестовое при «Отклике»).

    Всё в одной транзакции (NFR-03). Возвращает id созданного процесса.
    Начальный статус — этап; создать процесс сразу с итогом нельзя (SR1).
    """
    _validate_create_process(
        initiator=initiator, company_name=company_name, vacancy_title=vacancy_title,
        vacancy_url=vacancy_url, vacancy_source_code=vacancy_source_code,
        apply_channel_code=apply_channel_code, communication_channel_code=communication_channel_code,
        salary_from=salary_from, salary_to=salary_to,
        initial_status_code=initial_status_code, test_due_on=test_due_on,
    )

    own = conn is None
    if own:
        conn = get_connection()
    try:
        _ensure_reference_codes([
            ("directions", direction_code, "Направление"),
            ("channels", communication_channel_code, "Канал общения"),
            ("vacancy_sources", vacancy_source_code, "Источник вакансии"),
            ("channels", apply_channel_code, "Канал отклика"),
            ("employer_types", employer_type_code, "Тип работодателя"),
            ("employment_formats", employment_format_code, "Формат трудоустройства"),
        ], conn=conn)

        status_row = _fetch_one(
            "select kind, code from statuses where code = %(code)s",
            {"code": initial_status_code}, conn=conn,
        )
        if status_row is None:
            raise ValueError(f"Статус «{initial_status_code}» не найден в справочнике.")
        if status_row["kind"] != "stage":
            raise ValueError("Процесс нельзя создать сразу с итоговым статусом (SR1).")

        with conn.transaction():
            pid = conn.execute(CREATE_PROCESS_SQL, {
                "direction_code": direction_code,
                "initiator": initiator,
                "company_name": company_name.strip(),
                "vacancy_title": vacancy_title.strip(),
                "vacancy_url": vacancy_url or None,
                "vacancy_source_code": vacancy_source_code,
                "apply_channel_code": apply_channel_code,
                "communication_channel_code": communication_channel_code,
                "employer_type_code": employer_type_code,
                "employment_format_code": employment_format_code,
                "salary_from": salary_from,
                "salary_to": salary_to,
                "contact_name": contact_name or None,
                "contact_position": contact_position or None,
                "note": note or None,
                "initial_status_code": initial_status_code,
            }).fetchone()[0]

            conn.execute(INSERT_FIRST_HISTORY_SQL, {
                "pid": pid,
                "status_code": initial_status_code,
                "stage_date": initial_stage_date,
            })

            if initial_status_code == "APPLIED":
                conn.execute(INSERT_FIRST_TEST_SQL, {
                    "pid": pid,
                    "status_code": initial_status_code,
                    "received_on": initial_stage_date,
                    "due_on": test_due_on,
                })

        return pid
    finally:
        if own:
            conn.close()

# ---------------------------------------------------------------- запись: смена статуса и закрытие

STATUS_INFO_SQL = """
select id, code, name_ru, kind, stage_order, is_required_stage, in_funnel
  from statuses
 where code = %(code)s
"""

CURRENT_STATUS_SQL = """
select s.code, s.kind, s.name_ru
  from job_processes p join statuses s on s.id = p.status_id
 where p.id = %(pid)s
"""

HISTORY_STAGES_SQL = """
select s.code, s.kind, s.stage_order, s.is_required_stage
  from process_status_history h
  join statuses s on s.id = h.status_id
 where h.process_id = %(pid)s
"""

INSERT_STATUS_SQL = """
insert into process_status_history (process_id, status_id, stage_date, note, rejection_reason_id)
values (%(pid)s,
        (select id from statuses where code = %(status_code)s),
        %(stage_date)s,
        %(note)s,
        (select id from rejection_reasons where code = %(reason_code)s))
returning id
"""

# Коды предупреждений о нетипичном переходе (SR2, раздел 5 статусной модели)
WARN_REOPEN_CLOSED_PROCESS       = "REOPEN_CLOSED_PROCESS"
WARN_RETURN_TO_EARLIER_STAGE     = "RETURN_TO_EARLIER_STAGE"
WARN_SKIP_REQUIRED_STAGE         = "SKIP_REQUIRED_STAGE"
WARN_OFFER_OUTCOME_WITHOUT_OFFER = "OFFER_OUTCOME_WITHOUT_OFFER"
WARN_CHANGE_AFTER_FINAL_OFFER    = "CHANGE_AFTER_FINAL_OFFER"

FINAL_OFFER_OUTCOMES = ("OFFER_ACCEPTED", "OFFER_DECLINED")
REJECTION_OUTCOMES   = ("REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME")


def get_current_status(pid: int, conn: psycopg.Connection | None = None) -> dict | None:
    """Текущий статус процесса: code, kind, name_ru; None, если процесса нет."""
    return _fetch_one(CURRENT_STATUS_SQL, {"pid": pid}, conn=conn)


def get_status_info(status_code: str, conn: psycopg.Connection | None = None) -> dict | None:
    """Сведения о статусе справочника (kind, stage_order, name_ru…)."""
    return _fetch_one(STATUS_INFO_SQL, {"code": status_code}, conn=conn)


def _process_history_stages(pid: int, conn: psycopg.Connection | None = None) -> list[dict]:
    return _fetch_all(HISTORY_STAGES_SQL, {"pid": pid}, conn=conn)


def check_atypical_transition(pid: int, new_status_code: str,
                              conn: psycopg.Connection | None = None) -> list[tuple[str, str]]:
    """Предупреждения о нетипичном переходе (SR2, раздел 5 статусной модели).

    Возвращает список пар (код, текст); пустой список — переход типичный. Функция только
    читает данные и не блокирует переход: решение принимает пользователь (D14, R10).
    """
    warnings: list[tuple[str, str]] = []
    new = get_status_info(new_status_code, conn=conn)
    current = get_current_status(pid, conn=conn)
    if new is None or current is None:
        return warnings

    history = _process_history_stages(pid, conn=conn)
    stage_codes = {h["code"] for h in history if h["kind"] == "stage"}
    max_order = max((h["stage_order"] for h in history if h["kind"] == "stage"), default=0)

    # Возврат закрытого процесса в работу
    if current["kind"] == "outcome" and new["kind"] == "stage":
        warnings.append((WARN_REOPEN_CLOSED_PROCESS,
                         f"Закрытый процесс возвращается в работу: устанавливается этап «{new['name_ru']}»"))

    # Возврат на более ранний этап
    if new["kind"] == "stage" and new["stage_order"] is not None and max_order:
        if new["stage_order"] < max_order:
            warnings.append((WARN_RETURN_TO_EARLIER_STAGE,
                             f"Возврат на более ранний этап: «{new['name_ru']}» "
                             f"при достигнутом порядке {max_order}"))

    # Пропуск обязательного этапа
    if new["kind"] == "stage" and new["stage_order"] is not None:
        skipped = _fetch_all(
            "select code, name_ru from statuses "
            "where kind = 'stage' and is_required_stage and stage_order < %(order)s "
            "order by stage_order",
            {"order": new["stage_order"]}, conn=conn)
        missing = [s for s in skipped if s["code"] not in stage_codes]
        if missing:
            warnings.append((WARN_SKIP_REQUIRED_STAGE,
                             "Пропущен обязательный этап: "
                             + ", ".join(f"«{s['name_ru']}»" for s in missing)))

    # OFFER_ACCEPTED / OFFER_DECLINED, если в истории нет OFFER
    if new["code"] in FINAL_OFFER_OUTCOMES and "OFFER" not in stage_codes:
        warnings.append((WARN_OFFER_OUTCOME_WITHOUT_OFFER,
                         f"Устанавливается «{new['name_ru']}», но в истории нет этапа «Оффер»"))

    # Изменение статуса после OFFER_ACCEPTED / OFFER_DECLINED
    if current["code"] in FINAL_OFFER_OUTCOMES:
        warnings.append((WARN_CHANGE_AFTER_FINAL_OFFER,
                         f"Изменение статуса после «{current['name_ru']}»"))

    return warnings


def _insert_status_record(pid: int, status_code: str, stage_date: date,
                          note: str | None, reason_code: str | None,
                          conn: psycopg.Connection) -> int:
    return conn.execute(INSERT_STATUS_SQL, {
        "pid": pid, "status_code": status_code, "stage_date": stage_date,
        "note": note, "reason_code": reason_code,
    }).fetchone()[0]


def _qualifies_for_rejection_reason(pid: int, conn: psycopg.Connection) -> bool:
    """SR9: причина обязательна, если в истории есть этап воронки или тестовое задание."""
    row = _fetch_one("""
        select
            exists (select 1 from process_status_history h
                      join statuses s on s.id = h.status_id
                     where h.process_id = %(pid)s and s.in_funnel)            as has_funnel_stage,
            exists (select 1 from test_assignments where process_id = %(pid)s) as has_tests
    """, {"pid": pid}, conn=conn)
    return bool(row and (row["has_funnel_stage"] or row["has_tests"]))


def update_process_status(pid: int, status_code: str, stage_date: date,
                          note: str | None = None,
                          confirm_atypical: bool = False,
                          conn: psycopg.Connection | None = None) -> list[tuple[str, str]]:
    """Устанавливает этап процесса (US-04): добавляет запись истории; статус пересчитает триггер.

    Возвращает список предупреждений (нетипичный переход). Если предупреждения есть,
    а confirm_atypical=False, запись не выполняется и поднимается ValueError.
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        status = get_status_info(status_code, conn=conn)
        if status is None:
            raise ValueError(f"Статус «{status_code}» не найден в справочнике.")
        if status["kind"] != "stage":
            raise ValueError(f"«{status['name_ru']}» — итог; для закрытия используйте close_process().")

        warnings = check_atypical_transition(pid, status_code, conn=conn)
        if warnings and not confirm_atypical:
            texts = "; ".join(text for _, text in warnings)
            raise ValueError(f"Нетипичный переход требует подтверждения: {texts}")

        with conn.transaction():
            _insert_status_record(pid, status_code, stage_date, note or None, None, conn)
        return warnings
    finally:
        if own:
            conn.close()


def close_process(pid: int, outcome_code: str, stage_date: date,
                  rejection_reason_code: str | None = None,
                  note: str | None = None,
                  confirm_atypical: bool = False,
                  conn: psycopg.Connection | None = None) -> list[tuple[str, str]]:
    """Закрывает процесс итогом (US-06).

    Причина отказа (SR9): обязательна для REJECTED_BY_EMPLOYER и WITHDRAWN_BY_ME, если в истории
    есть этап воронки или тестовое задание; для NO_RESPONSE, OFFER_ACCEPTED, OFFER_DECLINED — не
    допускается.
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        status = get_status_info(outcome_code, conn=conn)
        if status is None:
            raise ValueError(f"Статус «{outcome_code}» не найден в справочнике.")
        if status["kind"] != "outcome":
            raise ValueError(f"«{status['name_ru']}» — этап; для этапа используйте update_process_status().")

        if outcome_code in REJECTION_OUTCOMES:
            if _qualifies_for_rejection_reason(pid, conn) and not rejection_reason_code:
                raise ValueError("Для отказа после интервью или тестового задания укажите "
                                 "причину (SR9).")
            if rejection_reason_code:
                reason = _fetch_one("select code from rejection_reasons where code = %(code)s",
                                    {"code": rejection_reason_code}, conn=conn)
                if reason is None:
                    raise ValueError(f"Причина отказа «{rejection_reason_code}» не найдена.")
        else:
            if rejection_reason_code:
                raise ValueError("Причина отказа допустима только для REJECTED_BY_EMPLOYER "
                                 "и WITHDRAWN_BY_ME (INV-08).")

        warnings = check_atypical_transition(pid, outcome_code, conn=conn)
        if warnings and not confirm_atypical:
            texts = "; ".join(text for _, text in warnings)
            raise ValueError(f"Нетипичный переход требует подтверждения: {texts}")

        with conn.transaction():
            _insert_status_record(pid, outcome_code, stage_date, note or None,
                                  rejection_reason_code, conn)
        return warnings
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------- запись: правка полей, дат этапов, удаление

UPDATE_PROCESS_SQL = """
update job_processes
   set direction_id = (select id from directions            where code = %(direction_code)s),
       company_name = %(company_name)s,
       vacancy_title = %(vacancy_title)s,
       vacancy_url = %(vacancy_url)s,
       vacancy_source_id = (select id from vacancy_sources  where code = %(vacancy_source_code)s),
       apply_channel_id = (select id from channels           where code = %(apply_channel_code)s),
       communication_channel_id = (select id from channels   where code = %(communication_channel_code)s),
       employer_type_id = (select id from employer_types     where code = %(employer_type_code)s),
       employment_format_id = (select id from employment_formats where code = %(employment_format_code)s),
       salary_from = %(salary_from)s,
       salary_to = %(salary_to)s,
       contact_name = %(contact_name)s,
       contact_position = %(contact_position)s,
       note = %(note)s
 where id = %(pid)s
"""


def update_process_fields(
    pid: int,
    *,
    direction_code: str,
    company_name: str,
    vacancy_title: str,
    communication_channel_code: str,
    vacancy_url: str | None = None,
    vacancy_source_code: str | None = None,
    apply_channel_code: str | None = None,
    employer_type_code: str | None = None,
    employment_format_code: str | None = None,
    salary_from: int | None = None,
    salary_to: int | None = None,
    contact_name: str | None = None,
    contact_position: str | None = None,
    note: str | None = None,
    conn: psycopg.Connection | None = None,
) -> None:
    """Правка полей карточки (US-05, критерий 1).

    Инициатор не меняется (INV-19): его значение читается из базы и используется в валидациях.
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select initiator from job_processes where id = %(pid)s",
                         {"pid": pid}, conn=conn)
        if row is None:
            raise ValueError(f"Процесс id={pid} не найден.")

        _validate_common_fields(
            initiator=row["initiator"],
            company_name=company_name, vacancy_title=vacancy_title,
            vacancy_url=vacancy_url, vacancy_source_code=vacancy_source_code,
            apply_channel_code=apply_channel_code,
            communication_channel_code=communication_channel_code,
            salary_from=salary_from, salary_to=salary_to,
        )

        _ensure_reference_codes([
            ("directions", direction_code, "Направление"),
            ("channels", communication_channel_code, "Канал общения"),
            ("vacancy_sources", vacancy_source_code, "Источник вакансии"),
            ("channels", apply_channel_code, "Канал отклика"),
            ("employer_types", employer_type_code, "Тип работодателя"),
            ("employment_formats", employment_format_code, "Формат трудоустройства"),
        ], conn=conn)

        with conn.transaction():
            conn.execute(UPDATE_PROCESS_SQL, {
                "pid": pid,
                "direction_code": direction_code,
                "company_name": company_name.strip(),
                "vacancy_title": vacancy_title.strip(),
                "vacancy_url": vacancy_url or None,
                "vacancy_source_code": vacancy_source_code,
                "apply_channel_code": apply_channel_code,
                "communication_channel_code": communication_channel_code,
                "employer_type_code": employer_type_code,
                "employment_format_code": employment_format_code,
                "salary_from": salary_from,
                "salary_to": salary_to,
                "contact_name": contact_name or None,
                "contact_position": contact_position or None,
                "note": note or None,
            })
    finally:
        if own:
            conn.close()


def update_history_record(
    history_id: int,
    *,
    stage_date: date,
    note: str | None = None,
    conn: psycopg.Connection | None = None,
) -> None:
    """Правка даты и комментария записи истории (US-05, D22).

    Прежнее значение не сохраняется. Порядок записей триггером не пересчитывается:
    он опирается на recorded_at, а не на stage_date.
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from process_status_history where id = %(id)s",
                         {"id": history_id}, conn=conn)
        if row is None:
            raise ValueError(f"Запись истории id={history_id} не найдена.")
        with conn.transaction():
            conn.execute(
                "update process_status_history set stage_date = %(d)s, note = %(note)s "
                "where id = %(id)s",
                {"id": history_id, "d": stage_date, "note": note or None})
    finally:
        if own:
            conn.close()


def delete_history_record(history_id: int,
                          conn: psycopg.Connection | None = None) -> None:
    """Удаляет запись истории (US-05, критерий 3).

    Если запись единственная, триггер `process_status_history_protect_last` поднимет ошибку
    (INV-18). После удаления триггер `process_status_history_sync_status` пересчитает
    job_processes.status_id по оставшейся последней записи (INV-10).
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from process_status_history where id = %(id)s",
                         {"id": history_id}, conn=conn)
        if row is None:
            raise ValueError(f"Запись истории id={history_id} не найдена.")
        with conn.transaction():
            conn.execute("delete from process_status_history where id = %(id)s",
                         {"id": history_id})
    finally:
        if own:
            conn.close()


def delete_process(pid: int, conn: psycopg.Connection | None = None) -> None:
    """Удаляет процесс каскадом: история, тестовые задания, связи с навыками (US-05, DM-06)."""
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from job_processes where id = %(pid)s",
                         {"pid": pid}, conn=conn)
        if row is None:
            raise ValueError(f"Процесс id={pid} не найден.")
        with conn.transaction():
            conn.execute("delete from job_processes where id = %(pid)s", {"pid": pid})
    finally:
        if own:
            conn.close()

# ---------------------------------------------------------------- запись: тестовые задания (US-07)

INSERT_TEST_ASSIGNMENT_SQL = """
insert into test_assignments
    (process_id, status_id, received_on, due_on, submitted_on, result_note)
values
    (%(pid)s,
     (select status_id from job_processes where id = %(pid)s),
     %(received_on)s, %(due_on)s, %(submitted_on)s, %(result_note)s)
returning id
"""

UPDATE_TEST_ASSIGNMENT_SQL = """
update test_assignments
   set received_on = %(received_on)s,
       due_on = %(due_on)s,
       submitted_on = %(submitted_on)s,
       result_note = %(result_note)s
 where id = %(test_id)s
"""


def _validate_test_dates(received_on: date, due_on: date | None, submitted_on: date | None) -> None:
    """INV-13: срок сдачи и дата сдачи не раньше даты получения."""
    if due_on is not None and due_on < received_on:
        raise ValueError("Срок сдачи тестового задания не может быть раньше даты получения (INV-13).")
    if submitted_on is not None and submitted_on < received_on:
        raise ValueError("Дата сдачи тестового задания не может быть раньше даты получения (INV-13).")


def add_test_assignment(
    pid: int,
    *,
    received_on: date,
    due_on: date | None = None,
    result_note: str | None = None,
    conn: psycopg.Connection | None = None,
) -> int:
    """Добавляет тестовое задание процессу (US-07, критерий 1).

    status_id = текущий статус процесса на момент добавления (SR7, не пересчитывается).
    Возвращает id созданной записи.
    """
    _validate_test_dates(received_on, due_on, None)

    own = conn is None
    if own:
        conn = get_connection()
    try:
        process = _fetch_one("select status_id from job_processes where id = %(pid)s",
                             {"pid": pid}, conn=conn)
        if process is None:
            raise ValueError(f"Процесс id={pid} не найден.")

        with conn.transaction():
            test_id = conn.execute(INSERT_TEST_ASSIGNMENT_SQL, {
                "pid": pid,
                "received_on": received_on,
                "due_on": due_on,
                "submitted_on": None,
                "result_note": result_note or None,
            }).fetchone()[0]
        return test_id
    finally:
        if own:
            conn.close()


def update_test_assignment(
    test_id: int,
    *,
    received_on: date,
    due_on: date | None = None,
    submitted_on: date | None = None,
    result_note: str | None = None,
    conn: psycopg.Connection | None = None,
) -> None:
    """Правка тестового задания: все поля (US-07, критерий 4)."""
    _validate_test_dates(received_on, due_on, submitted_on)

    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from test_assignments where id = %(id)s",
                         {"id": test_id}, conn=conn)
        if row is None:
            raise ValueError(f"Тестовое задание id={test_id} не найдено.")

        with conn.transaction():
            conn.execute(UPDATE_TEST_ASSIGNMENT_SQL, {
                "test_id": test_id,
                "received_on": received_on,
                "due_on": due_on,
                "submitted_on": submitted_on,
                "result_note": result_note or None,
            })
    finally:
        if own:
            conn.close()


def mark_test_submitted(
    test_id: int,
    *,
    submitted_on: date,
    result_note: str | None = None,
    conn: psycopg.Connection | None = None,
) -> None:
    """Отметка «сдано» + результат (US-07, критерий 2).

    Дата сдачи не раньше даты получения (INV-13).
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select received_on from test_assignments where id = %(id)s",
                         {"id": test_id}, conn=conn)
        if row is None:
            raise ValueError(f"Тестовое задание id={test_id} не найдено.")
        _validate_test_dates(row["received_on"], None, submitted_on)

        with conn.transaction():
            conn.execute(
                "update test_assignments set submitted_on = %(submitted_on)s, "
                "result_note = coalesce(%(result_note)s, result_note) where id = %(id)s",
                {"id": test_id, "submitted_on": submitted_on,
                 "result_note": result_note or None})
    finally:
        if own:
            conn.close()


def delete_test_assignment(test_id: int,
                           conn: psycopg.Connection | None = None) -> None:
    """Удаляет тестовое задание (US-07, критерий 4)."""
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from test_assignments where id = %(id)s",
                         {"id": test_id}, conn=conn)
        if row is None:
            raise ValueError(f"Тестовое задание id={test_id} не найдено.")
        with conn.transaction():
            conn.execute("delete from test_assignments where id = %(id)s",
                         {"id": test_id})
    finally:
        if own:
            conn.close()


def get_process_tests(pid: int,
                      conn: psycopg.Connection | None = None) -> list[dict]:
    """Тестовые задания процесса (US-07, критерий 4): все, в порядке получения."""
    return _fetch_all("""
        select t.id, t.received_on, t.due_on, t.submitted_on, t.result_note,
               s.name_ru as status_at_receipt,
               (t.submitted_on is null and t.due_on is not null
                and t.due_on >= current_date) as is_scheduled
          from test_assignments t
          join statuses s on s.id = t.status_id
         where t.process_id = %(pid)s
         order by t.received_on, t.id
    """, {"pid": pid}, conn=conn)

# ---------------------------------------------------------------- запись: навыки (US-11)

DELETE_PROCESS_SKILLS_SQL = "delete from process_skills where process_id = %(pid)s"

INSERT_PROCESS_SKILL_SQL = """
insert into process_skills (process_id, skill_id) values (%(pid)s, %(sid)s)
"""

DELETE_PROFILE_SKILLS_SQL = """
delete from profile_skills
 where direction_id = (select id from directions where code = %(code)s)
"""

INSERT_PROFILE_SKILL_SQL = """
insert into profile_skills (direction_id, skill_id)
values ((select id from directions where code = %(code)s), %(sid)s)
"""


def _normalize_skill_names(skill_names: list[str]) -> list[str]:
    """Приводит имена навыков к виду «без пробелов по краям, без дублей без учёта регистра».

    Первое написание сохраняется, последующие дубликаты (в том числе в другом регистре)
    отбрасываются (INV-14, US-11 критерий 3).
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in skill_names:
        clean = (name or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _resolve_skill_id(name: str, conn: psycopg.Connection) -> int:
    """id навыка по имени без учёта регистра; создаёт навык, если его нет (INV-14)."""
    row = conn.execute("select id from skills where lower(name) = lower(%(name)s)",
                       {"name": name}).fetchone()
    if row is not None:
        return row[0]
    row = conn.execute("insert into skills (name) values (%(name)s) returning id",
                       {"name": name}).fetchone()
    return row[0]


def set_process_skills(pid: int, skill_names: list[str],
                       conn: psycopg.Connection | None = None) -> list[str]:
    """Заменяет набор навыков вакансии у процесса (US-11, критерий 3).

    Возвращает фактически сохранённые названия после нормализации.
    Навыки хранятся у процесса независимо от текущего статуса; в рейтинг Q5/Q6
    попадут только процессы с HR-интервью и позже (INV-17, D8).
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = _fetch_one("select 1 from job_processes where id = %(pid)s",
                         {"pid": pid}, conn=conn)
        if row is None:
            raise ValueError(f"Процесс id={pid} не найден.")

        normalized = _normalize_skill_names(skill_names)
        with conn.transaction():
            conn.execute(DELETE_PROCESS_SKILLS_SQL, {"pid": pid})
            for name in normalized:
                sid = _resolve_skill_id(name, conn)
                conn.execute(INSERT_PROCESS_SKILL_SQL, {"pid": pid, "sid": sid})
        return normalized
    finally:
        if own:
            conn.close()


def set_profile_skills(direction_code: str, skill_names: list[str],
                       conn: psycopg.Connection | None = None) -> list[str]:
    """Заменяет профиль навыков направления (D3, US-11, критерий 6).

    Профили направлений независимы. Возвращает нормализованный список.
    """
    own = conn is None
    if own:
        conn = get_connection()
    try:
        dir_row = _fetch_one("select id from directions where code = %(code)s",
                             {"code": direction_code}, conn=conn)
        if dir_row is None:
            raise ValueError(f"Направление «{direction_code}» не найдено.")
        direction_id = dir_row["id"]

        normalized = _normalize_skill_names(skill_names)
        with conn.transaction():
            conn.execute("delete from profile_skills where direction_id = %(did)s",
                         {"did": direction_id})
            for name in normalized:
                sid = _resolve_skill_id(name, conn)
                conn.execute("insert into profile_skills (direction_id, skill_id) "
                             "values (%(did)s, %(sid)s)",
                             {"did": direction_id, "sid": sid})
        return normalized
    finally:
        if own:
            conn.close()


def get_process_skills(pid: int, conn: psycopg.Connection | None = None) -> list[str]:
    """Навыки процесса (для карточки и тестов)."""
    return [row["name"] for row in _fetch_all("""
        select sk.name
          from process_skills ps
          join skills sk on sk.id = ps.skill_id
         where ps.process_id = %(pid)s
         order by lower(sk.name)
    """, {"pid": pid}, conn=conn)]


def get_direction_profile_skills(direction_code: str,
                                 conn: psycopg.Connection | None = None) -> list[str]:
    """Профиль навыков направления (D3)."""
    return [row["name"] for row in _fetch_all("""
        select sk.name
          from profile_skills pf
          join skills sk on sk.id = pf.skill_id
          join directions d on d.id = pf.direction_id
         where d.code = %(code)s
         order by lower(sk.name)
    """, {"code": direction_code}, conn=conn)]


def get_direction_skill_suggestions(direction_code: str,
                                    conn: psycopg.Connection | None = None) -> list[str]:
    """Навыки, встречавшиеся у процессов этого направления (US-11, критерий 3).

    Используется для подсказок при вводе. Сортировка без учёта регистра.
    GROUP BY вместо DISTINCT: PostgreSQL разрешает ORDER BY по выражению от группируемой колонки,
    но не разрешает его при DISTINCT, если выражения нет в списке выборки.
    """
    return [row["name"] for row in _fetch_all("""
        select sk.name
          from process_skills ps
          join skills sk on sk.id = ps.skill_id
          join job_processes p on p.id = ps.process_id
          join directions d on d.id = p.direction_id
         where d.code = %(code)s
         group by sk.name
         order by lower(sk.name)
    """, {"code": direction_code}, conn=conn)]