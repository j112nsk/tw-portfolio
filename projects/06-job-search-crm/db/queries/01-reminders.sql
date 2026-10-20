-- =====================================================================
-- 01-reminders.sql
-- Вопрос Q4 (US-08, US-09): что запланировано на сегодня–завтра и на ближайшие 7 дней, и какие
-- открытые процессы остались без запланированного этапа.
-- Правила: SR13 (запланированный этап), D17, D24, D27. Запрос только читает данные (NFR-07).
-- D32: сроки сдачи тестовых больше не напоминаются — тестовое это обычный этап.
-- Параметр: today (текущая дата; в приложении это date.today()).
-- Группы: today_tomorrow (сегодня и завтра), next_7_days (от сегодня + 2 до сегодня + 7),
--         no_planned_stage (у открытого процесса нет этапа с датой не раньше сегодняшней).
-- =====================================================================

select q.*
  from (
        with open_proc as (
            -- открытые процессы: текущий статус — этап
            select p.id, p.company_name, p.vacancy_title, d.code as direction
              from job_processes p
              join statuses cs on cs.id = p.status_id and cs.kind = 'stage'
              join directions d on d.id = p.direction_id
        ),
        events as (
            -- запланированные этапы (тестовое — тоже этап, D32)
            select o.id as process_id, h.stage_date as event_date,
                   'stage' as event_kind, s.name_ru as event_name
              from open_proc o
              join process_status_history h on h.process_id = o.id
              join statuses s on s.id = h.status_id and s.kind = 'stage'
             where h.stage_date >= %(today)s::date
        )
        select case when e.event_date <= %(today)s::date + 1
                    then 'today_tomorrow' else 'next_7_days' end as group_code,
               e.event_date,
               o.id as process_id,
               o.company_name,
               o.vacancy_title,
               o.direction,
               e.event_kind,
               e.event_name,
               null::integer as days_since_last_stage
          from events e
          join open_proc o on o.id = e.process_id
         where e.event_date <= %(today)s::date + 7

        union all

        select 'no_planned_stage',
               last_stage.last_stage_date,
               o.id,
               o.company_name,
               o.vacancy_title,
               o.direction,
               'none',
               'Нет запланированного этапа',
               %(today)s::date - last_stage.last_stage_date
          from open_proc o
          cross join lateral (
                select max(h.stage_date) as last_stage_date
                  from process_status_history h
                  join statuses s on s.id = h.status_id and s.kind = 'stage'
                 where h.process_id = o.id
          ) last_stage
         where not exists (select 1 from events e where e.process_id = o.id)
       ) q
 order by case q.group_code
              when 'today_tomorrow' then 1
              when 'next_7_days' then 2
              else 3
          end,
          q.event_date,
          q.company_name;