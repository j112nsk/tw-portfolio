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

    if initial_status_code == "APPLIED":
        if test_due_on is not None and test_due_on < date.today():
            pass  # допускаем: тестовое могло быть выдано раньше, чем создаётся запись
    else:
        if test_due_on is not None:
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
        # Начальный статус должен быть этапом (SR1)
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
                # US-01, критерий 5 и INV-20: при начальном «Отклике» тестовое обязательно.
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