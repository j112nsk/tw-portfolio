-- =====================================================================
-- 08-salaries.sql
-- Вопрос Q7 (US-18): какие зарплатные вилки («на руки», руб.) указаны или выяснены на этапах.
-- Правила: D15, R8, R14: только процессы, где вилка известна; середина вилки = среднее границ (если задана одна, берётся она).
-- Параметры (None = без фильтра): initiator ('applicant' / 'employer'), date_from, date_to
-- (по дате начала процесса), source, apply_channel, employer_type, employment_format (коды справочников).
-- =====================================================================
-- Колонки: scope (направление или ALL), n (процессов с вилкой), min_mid, median_mid, max_mid (середина вилки, руб.).

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
            select max(s.stage_order) filter (where s.in_funnel) as max_order,
                   bool_or(s.code = 'TEAM_MEETING')    as had_team,
                   bool_or(s.code = 'SECURITY_CHECK')  as had_security
              from process_status_history h
              join statuses s on s.id = h.status_id
             where h.process_id = f.id
      ) m on true
),
mids as (
    select f.direction,
           (coalesce(p.salary_from, p.salary_to) + coalesce(p.salary_to, p.salary_from)) / 2.0 as mid
      from filtered f
      join job_processes p on p.id = f.id
     where p.salary_from is not null or p.salary_to is not null
)
select coalesce(direction, 'ALL') as scope,
       count(*) as n,
       round(min(mid), 0) as min_mid,
       round((percentile_cont(0.5) within group (order by mid))::numeric, 0) as median_mid,
       round(max(mid), 0) as max_mid
  from mids
 group by grouping sets ((direction), ())
 order by (direction is null), scope;
