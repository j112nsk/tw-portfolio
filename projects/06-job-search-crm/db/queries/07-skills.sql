-- =====================================================================
-- 07-skills.sql
-- Вопросы Q5 и Q6 (US-17): частые навыки в вакансиях, дошедших до интервью, и навыки, которых нет в профиле.
-- Правила: D3, D8, INV-17, R8: учитываются процессы, в истории которых есть HR-интервью или более поздний этап, с навыками.
-- Параметры (None = без фильтра): initiator ('applicant' / 'employer'), date_from, date_to
-- (по дате начала процесса), source, apply_channel, employer_type, employment_format (коды справочников).
-- =====================================================================
-- Колонки: direction, skill, n_processes, share_pct (от процессов направления с навыками), in_profile (есть ли навык
-- в профиле направления; пробелы = in_profile false), n_sample (процессов с навыками в направлении).

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
sample as (
    select f.direction_id, count(*) as n_sample
      from flags f
     where f.reached_hr
       and exists (select 1 from process_skills ps where ps.process_id = f.id)
     group by f.direction_id
)
select f.direction,
       sk.name as skill,
       count(*) as n_processes,
       round(100.0 * count(*) / sm.n_sample, 1) as share_pct,
       exists (select 1
                 from profile_skills pf
                where pf.direction_id = f.direction_id and pf.skill_id = sk.id) as in_profile,
       sm.n_sample
  from flags f
  join process_skills ps on ps.process_id = f.id
  join skills sk on sk.id = ps.skill_id
  join sample sm on sm.direction_id = f.direction_id
 where f.reached_hr
 group by f.direction, f.direction_id, sk.id, sk.name, sm.n_sample
 order by f.direction, count(*) desc, sk.name;
