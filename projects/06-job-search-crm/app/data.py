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

def _fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_one(sql: str, params: dict | None = None) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchone()
    finally:
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