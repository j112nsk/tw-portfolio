-- =====================================================================
-- 00-integrity-checks.sql
-- Проверка согласованности данных (правила, которые не контролирует база
-- ограничениями): INV-08 (обязательность причины отказа), INV-09, INV-10, INV-20.
-- Результат: по одной строке на каждое нарушение. Пустой результат = данные согласованы.
-- Запуск: python -m db.check_integrity
-- =====================================================================

with first_rec as (
    -- первая запись истории каждого процесса (порядок: recorded_at, затем id)
    select distinct on (h.process_id)
           h.process_id, h.status_id
      from process_status_history h
     order by h.process_id, h.recorded_at, h.id
),
last_rec as (
    -- последняя запись истории каждого процесса
    select distinct on (h.process_id)
           h.process_id, h.status_id, h.rejection_reason_id
      from process_status_history h
     order by h.process_id, h.recorded_at desc, h.id desc
)

-- INV-09: у процесса есть хотя бы одна запись истории
select 'INV-09' as rule, p.id as process_id, p.company_name,
       'у процесса нет ни одной записи истории' as details
  from job_processes p
 where not exists (select 1 from process_status_history h where h.process_id = p.id)

union all

-- INV-09: первая запись истории — этап, а не итог
select 'INV-09', p.id, p.company_name,
       'первая запись истории не является этапом'
  from job_processes p
  join first_rec f on f.process_id = p.id
  join statuses s on s.id = f.status_id
 where s.kind <> 'stage'

union all

-- INV-10: текущий статус равен статусу последней записи истории
select 'INV-10', p.id, p.company_name,
       'текущий статус не совпадает с последней записью истории'
  from job_processes p
  join last_rec l on l.process_id = p.id
 where p.status_id <> l.status_id

union all

-- INV-08: отказ после интервью или тестового без причины
select 'INV-08', p.id, p.company_name,
       'процесс закрыт отказом после интервью или тестового, причина не указана'
  from job_processes p
  join statuses cs on cs.id = p.status_id
  join last_rec l on l.process_id = p.id
 where cs.code in ('REJECTED_BY_EMPLOYER', 'WITHDRAWN_BY_ME')
   and l.rejection_reason_id is null
   and (
        exists (select 1
                  from process_status_history h
                  join statuses s on s.id = h.status_id
                 where h.process_id = p.id and s.in_funnel)
        or exists (select 1 from test_assignments t where t.process_id = p.id)
   )

union all

-- INV-20: процесс начат с «Отклика», но тестового задания нет
select 'INV-20', p.id, p.company_name,
       'процесс начат с «Отклика», но у него нет тестового задания'
  from job_processes p
  join first_rec f on f.process_id = p.id
  join statuses s on s.id = f.status_id
 where s.code = 'APPLIED'
   and not exists (select 1 from test_assignments t where t.process_id = p.id)

order by rule, process_id;
