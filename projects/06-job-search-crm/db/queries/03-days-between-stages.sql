-- =====================================================================
-- 03-days-between-stages.sql
-- Вопрос Q2 (US-13): сколько календарных дней проходит между этапами.
-- Правила: SR12 (дата первой записи каждого этапа), D21, D29 (календарные дни). Пары с отрицательной разницей исключаются.
-- Параметры (None = без фильтра): initiator ('applicant' / 'employer'), date_from, date_to
-- (по дате начала процесса), source, apply_channel, employer_type, employment_format (коды справочников).
-- =====================================================================
-- Колонки: scope (направление или ALL), pair (HR_TO_TECH, TECH_TO_OFFER), n (процессов в расчёте),
-- avg_days, median_days, excluded_negative (число исключённых пар с отрицательной разницей).

with thresholds as (
    select (select stage_order from statuses where code = 'APPLIED')        as applied_order,
           (select stage_order from statuses where code = 'HR_INTERVIEW')   as hr_order,
           (select stage_order from statuses where code = 'TECH_INTERVIEW') as tech_order,
           (select stage_order from statuses where code = 'OFFER')          as offer_order
),
proc as (
    -- процессы с кодами справочников; дата начала = первая дата этапа в истории (D21)
    select p.id,
           p.direction_id,
           d.code  as direction,
           p.initiator,
           vs.code as source_code,
           ac.code as apply_channel_code,
           cc.code as comm_channel_code,
           et.code as employer_type_code,
           ef.code as employment_format_code,
           (select min(h.stage_date)
              from process_status_history h
              join statuses s on s.id = h.status_id
             where h.process_id = p.id and s.kind = 'stage') as start_date
      from job_processes p
      join directions d on d.id = p.direction_id
      join channels cc on cc.id = p.communication_channel_id
      left join vacancy_sources vs on vs.id = p.vacancy_source_id
      left join channels ac on ac.id = p.apply_channel_id
      left join employer_types et on et.id = p.employer_type_id
      left join employment_formats ef on ef.id = p.employment_format_id
),
filtered as (
    -- необязательные фильтры: значение NULL означает «без фильтра»
    select pr.*
      from proc pr
     where (%(initiator)s::text is null or pr.initiator = %(initiator)s::text)
       and (%(date_from)s::date is null or pr.start_date >= %(date_from)s::date)
       and (%(date_to)s::date   is null or pr.start_date <= %(date_to)s::date)
       and (%(source)s::text            is null or pr.source_code = %(source)s::text)
       and (%(apply_channel)s::text     is null or pr.apply_channel_code = %(apply_channel)s::text)
       and (%(employer_type)s::text     is null or pr.employer_type_code = %(employer_type)s::text)
       and (%(employment_format)s::text is null or pr.employment_format_code = %(employment_format)s::text)
),
flags as (
    -- до каких этапов дошёл процесс по истории, а не по текущему статусу (SR11, D14)
    select f.*,
           coalesce(m.max_order, 0) >= t.hr_order    as reached_hr,
           coalesce(m.max_order, 0) >= t.tech_order  as reached_tech,
           coalesce(m.max_order, 0) >= t.offer_order as reached_offer,
           coalesce(m.had_team, false)               as had_team,
           coalesce(m.had_security, false)           as had_security,
           coalesce(m.max_order, 0) = t.applied_order as only_test
      from filtered f
      cross join thresholds t
      left join lateral (
            select max(s.stage_order)                  as max_order,
                   bool_or(s.code = 'TEAM_MEETING')    as had_team,
                   bool_or(s.code = 'SECURITY_CHECK')  as had_security
              from process_status_history h
              join statuses s on s.id = h.status_id
             where h.process_id = f.id
      ) m on true
),
dates as (
    select f.id, f.direction,
           min(h.stage_date) filter (where s.code = 'HR_INTERVIEW')   as hr_date,
           min(h.stage_date) filter (where s.code = 'TECH_INTERVIEW') as tech_date,
           min(h.stage_date) filter (where s.code = 'OFFER')          as offer_date
      from filtered f
      join process_status_history h on h.process_id = f.id
      join statuses s on s.id = h.status_id
     group by f.id, f.direction
),
pairs as (
    select direction, 'HR_TO_TECH' as pair, tech_date - hr_date as days
      from dates
     where hr_date is not null and tech_date is not null
    union all
    select direction, 'TECH_TO_OFFER', offer_date - tech_date
      from dates
     where tech_date is not null and offer_date is not null
)
select coalesce(direction, 'ALL') as scope,
       pair,
       count(*) filter (where days >= 0) as n,
       round(avg(days) filter (where days >= 0), 1) as avg_days,
       round((percentile_cont(0.5) within group (order by days) filter (where days >= 0))::numeric, 1) as median_days,
       count(*) filter (where days < 0) as excluded_negative
  from pairs
 group by grouping sets ((direction, pair), (pair))
 order by (direction is null), scope, pair;
