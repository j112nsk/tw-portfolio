-- =====================================================================
-- 003_triggers.sql
-- Job Search CRM: триггеры для правил, которые нельзя выразить ограничениями.
--   INV-04  канал отклика должен быть каналом, которым можно откликнуться
--   INV-08  причина отказа допустима только у записей об отказе
--   INV-10  текущий статус процесса = статус последней записи истории
--   INV-18  нельзя удалить единственную запись истории процесса
-- =====================================================================


-- ---------------------------------------------------------------------
-- INV-04: apply_channel_id ссылается только на канал с is_apply_channel
-- ---------------------------------------------------------------------

create or replace function fn_job_processes_check_channels()
returns trigger
language plpgsql
as $$
begin
    if new.apply_channel_id is not null
       and not exists (
            select 1
              from channels c
             where c.id = new.apply_channel_id
               and c.is_apply_channel
       )
    then
        raise exception 'Канал с id=% нельзя использовать как канал отклика', new.apply_channel_id
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger job_processes_check_channels
    before insert or update of apply_channel_id on job_processes
    for each row
    execute function fn_job_processes_check_channels();


-- ---------------------------------------------------------------------
-- INV-08 (часть): причина отказа только у записей «Отказ работодателя»
-- и «Мой отказ». Обязательность причины проверяет приложение (SR9).
-- ---------------------------------------------------------------------

create or replace function fn_status_history_check_rejection()
returns trigger
language plpgsql
as $$
declare
    v_code text;
begin
    if new.rejection_reason_id is not null then
        select s.code into v_code
          from statuses s
         where s.id = new.status_id;

        if coalesce(v_code, '') not in ('REJECTED_BY_EMPLOYER', 'WITHDRAWN_BY_ME') then
            raise exception 'Причина отказа допустима только для статусов REJECTED_BY_EMPLOYER и WITHDRAWN_BY_ME'
                using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

create trigger process_status_history_check_rejection
    before insert or update of status_id, rejection_reason_id on process_status_history
    for each row
    execute function fn_status_history_check_rejection();


-- ---------------------------------------------------------------------
-- INV-10: job_processes.status_id всегда равен статусу последней записи
-- истории (порядок: recorded_at, затем id). Приложение только добавляет,
-- меняет и удаляет записи истории; текущий статус пересчитывается здесь.
-- ---------------------------------------------------------------------

create or replace function fn_status_history_sync_status()
returns trigger
language plpgsql
as $$
declare
    v_process bigint;
    v_status  smallint;
begin
    if tg_op = 'DELETE' then
        v_process := old.process_id;
    else
        v_process := new.process_id;
    end if;

    select h.status_id into v_status
      from process_status_history h
     where h.process_id = v_process
     order by h.recorded_at desc, h.id desc
     limit 1;

    -- Если записей не осталось (процесс удаляется каскадом), ничего не меняем.
    if v_status is not null then
        update job_processes
           set status_id = v_status
         where id = v_process
           and status_id is distinct from v_status;
    end if;

    return null;
end;
$$;

create trigger process_status_history_sync_status
    after insert or delete or update of status_id, recorded_at on process_status_history
    for each row
    execute function fn_status_history_sync_status();


-- ---------------------------------------------------------------------
-- INV-18: нельзя удалить единственную запись истории процесса.
-- При каскадном удалении процесса (вложенный вызов из триггера ссылочной
-- целостности) проверка не выполняется.
-- ---------------------------------------------------------------------

create or replace function fn_status_history_protect_last()
returns trigger
language plpgsql
as $$
begin
    if pg_trigger_depth() > 1 then
        return old;
    end if;

    if not exists (
            select 1
              from process_status_history h
             where h.process_id = old.process_id
               and h.id <> old.id
       )
    then
        raise exception 'Нельзя удалить единственную запись истории процесса id=%', old.process_id
            using errcode = 'restrict_violation';
    end if;

    return old;
end;
$$;

create trigger process_status_history_protect_last
    before delete on process_status_history
    for each row
    execute function fn_status_history_protect_last();
