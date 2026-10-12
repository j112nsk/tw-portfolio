-- =====================================================================
-- 05-slices.sql
-- Вопросы Q12 и Q13 (US-15): канал общения, тип работодателя, формат трудоустройства.
-- Правила: D12, D20, D30: процессы обоих инициаторов (фильтр по инициатору); APPLY_X_COMM только для начатых откликом.
-- Параметры (None = без фильтра): initiator ('applicant' / 'employer'), date_from, date_to
-- (по дате начала процесса), source, apply_channel, employer_type, employment_format (коды справочников).
-- =====================================================================
-- Колонки: direction, dimension (COMM_CHANNEL, APPLY_X_COMM, EMPLOYER_TYPE, EMPLOYMENT_FORMAT), value_1, value_2
-- (для APPLY_X_COMM: канал отклика и канал общения; NOT_SPECIFIED = не указано), n_processes, n_tech / pct_tech,
-- n_offer / pct_offer (доля от n_processes).

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
facts as (
    select direction, 'COMM_CHANNEL' as dimension, comm_channel_code as value_1, null::text as value_2,
           reached_tech, reached_offer
      from flags
    union all
    select direction, 'APPLY_X_COMM', apply_channel_code, comm_channel_code, reached_tech, reached_offer
      from flags
     where initiator = 'applicant'
    union all
    select direction, 'EMPLOYER_TYPE', coalesce(employer_type_code, 'NOT_SPECIFIED'), null::text,
           reached_tech, reached_offer
      from flags
    union all
    select direction, 'EMPLOYMENT_FORMAT', coalesce(employment_format_code, 'NOT_SPECIFIED'), null::text,
           reached_tech, reached_offer
      from flags
)
select direction,
       dimension,
       value_1,
       value_2,
       count(*)                                                    as n_processes,
       count(*) filter (where reached_tech)                        as n_tech,
       round(100.0 * count(*) filter (where reached_tech) / count(*), 1)  as pct_tech,
       count(*) filter (where reached_offer)                       as n_offer,
       round(100.0 * count(*) filter (where reached_offer) / count(*), 1) as pct_offer
  from facts
 group by direction, dimension, value_1, value_2
 order by direction, dimension, value_1, value_2;
