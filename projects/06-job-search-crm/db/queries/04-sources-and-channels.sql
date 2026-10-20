-- =====================================================================
-- 04-sources-and-channels.sql
-- Вопросы Q3 и Q9 (US-14): из каких источников вакансий и каналов отклика приходят процессы и докуда они доходят.
-- Правила: D11, D12, D30: считаются только процессы, начатые откликом соискателя; доли среди процессов в системе (риск R15).
-- Параметры (None = без фильтра): initiator ('applicant' / 'employer'), date_from, date_to
-- (по дате начала процесса), source, apply_channel, employer_type, employment_format (коды справочников).
-- =====================================================================
-- Колонки: direction, dimension (SOURCE / APPLY_CHANNEL), value_code, value_name, n_processes, share_pct (доля от
-- процессов направления, начатых откликом), n_tech / pct_tech, n_offer / pct_offer (доля от n_processes),
-- incoming_excluded (входящих процессов направления, в расчёт не вошли). Значения без процессов показаны с нулями.

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
dims as (
    select 'SOURCE' as dimension, code as value_code, name_ru as value_name, sort_order
      from vacancy_sources
    union all
    select 'APPLY_CHANNEL', code, name_ru, sort_order
      from channels
     where is_apply_channel
),
base as (
    select dr.id as direction_id, dr.code as direction, dm.dimension, dm.value_code, dm.value_name, dm.sort_order
      from directions dr
     cross join dims dm
),
facts as (
    select f.direction_id, 'SOURCE' as dimension, f.source_code as value_code, f.reached_tech, f.reached_offer
      from flags f
     where f.initiator = 'applicant'
    union all
    select f.direction_id, 'APPLY_CHANNEL', f.apply_channel_code, f.reached_tech, f.reached_offer
      from flags f
     where f.initiator = 'applicant'
),
totals as (
    select direction_id, count(*) as n_total
      from flags
     where initiator = 'applicant'
     group by direction_id
)
select b.direction,
       b.dimension,
       b.value_code,
       b.value_name,
       count(x.value_code)                                                  as n_processes,
       round(100.0 * count(x.value_code) / nullif(t.n_total, 0), 1)         as share_pct,
       count(*) filter (where x.reached_tech)                               as n_tech,
       round(100.0 * count(*) filter (where x.reached_tech)
             / nullif(count(x.value_code), 0), 1)                           as pct_tech,
       count(*) filter (where x.reached_offer)                              as n_offer,
       round(100.0 * count(*) filter (where x.reached_offer)
             / nullif(count(x.value_code), 0), 1)                           as pct_offer,
       (select count(*) from flags e
         where e.initiator = 'employer' and e.direction_id = b.direction_id) as incoming_excluded
  from base b
  left join facts x
         on x.direction_id = b.direction_id
        and x.dimension = b.dimension
        and x.value_code = b.value_code
  left join totals t on t.direction_id = b.direction_id
 group by b.direction_id, b.direction, b.dimension, b.value_code, b.value_name, b.sort_order, t.n_total
 order by b.direction, b.dimension, b.sort_order;
