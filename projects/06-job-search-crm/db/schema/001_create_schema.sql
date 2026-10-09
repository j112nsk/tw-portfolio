-- =====================================================================
-- 001_create_schema.sql
-- Job Search CRM: справочники, рабочие таблицы, индексы.
-- Модель: docs/data-model/01-logical-model.md и 02-physical-model.md
-- Целевая СУБД: PostgreSQL 14 или новее. Кодировка базы: UTF8.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Справочники
-- ---------------------------------------------------------------------

create table directions (
    id          smallint generated always as identity primary key,
    code        text     not null,
    name_ru     text     not null,
    sort_order  smallint not null,
    constraint directions_code_uk  unique (code),
    constraint directions_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint directions_name_chk check (btrim(name_ru) <> '')
);

create table vacancy_sources (
    id          smallint generated always as identity primary key,
    code        text     not null,
    name_ru     text     not null,
    sort_order  smallint not null,
    constraint vacancy_sources_code_uk  unique (code),
    constraint vacancy_sources_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint vacancy_sources_name_chk check (btrim(name_ru) <> '')
);

create table channels (
    id                smallint generated always as identity primary key,
    code              text     not null,
    name_ru           text     not null,
    sort_order        smallint not null,
    is_apply_channel  boolean  not null,
    constraint channels_code_uk  unique (code),
    constraint channels_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint channels_name_chk check (btrim(name_ru) <> '')
);

create table employer_types (
    id          smallint generated always as identity primary key,
    code        text     not null,
    name_ru     text     not null,
    sort_order  smallint not null,
    constraint employer_types_code_uk  unique (code),
    constraint employer_types_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint employer_types_name_chk check (btrim(name_ru) <> '')
);

create table employment_formats (
    id          smallint generated always as identity primary key,
    code        text     not null,
    name_ru     text     not null,
    sort_order  smallint not null,
    constraint employment_formats_code_uk  unique (code),
    constraint employment_formats_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint employment_formats_name_chk check (btrim(name_ru) <> '')
);

create table rejection_reasons (
    id          smallint generated always as identity primary key,
    code        text     not null,
    name_ru     text     not null,
    sort_order  smallint not null,
    constraint rejection_reasons_code_uk  unique (code),
    constraint rejection_reasons_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint rejection_reasons_name_chk check (btrim(name_ru) <> '')
);

create table statuses (
    id                 smallint generated always as identity primary key,
    code               text     not null,
    name_ru            text     not null,
    sort_order         smallint not null,
    kind               text     not null,
    stage_order        smallint,
    is_required_stage  boolean,
    constraint statuses_code_uk  unique (code),
    constraint statuses_code_chk check (code ~ '^[A-Z][A-Z0-9_]*$'),
    constraint statuses_name_chk check (btrim(name_ru) <> ''),
    constraint statuses_kind_chk check (kind in ('stage', 'outcome')),
    constraint statuses_stage_order_uk unique (stage_order),
    constraint statuses_stage_order_chk check (stage_order is null or stage_order > 0),
    constraint statuses_stage_chk check (
        (kind = 'stage'   and stage_order is not null and is_required_stage is not null)
     or (kind = 'outcome' and stage_order is null     and is_required_stage is null)
    )
);


-- ---------------------------------------------------------------------
-- Навыки
-- ---------------------------------------------------------------------

create table skills (
    id    integer generated always as identity primary key,
    name  text not null,
    constraint skills_name_chk check (name = btrim(name) and name <> '')
);

-- Название навыка уникально без учёта регистра (INV-14)
create unique index skills_name_ci_uk on skills (lower(name));


-- ---------------------------------------------------------------------
-- Процесс: отклик соискателя или входящий контакт работодателя
-- ---------------------------------------------------------------------

create table job_processes (
    id                        bigint   generated always as identity primary key,
    direction_id              smallint not null references directions (id),
    initiator                 text     not null,
    company_name              text     not null,
    vacancy_title             text     not null,
    vacancy_url               text,
    started_on                date     not null,
    vacancy_source_id         smallint references vacancy_sources (id),
    apply_channel_id          smallint references channels (id),
    has_cover_letter          boolean,
    employer_type_id          smallint references employer_types (id),
    employment_format_id      smallint references employment_formats (id),
    salary_from               integer,
    salary_to                 integer,
    first_response_on         date,
    communication_channel_id  smallint references channels (id),
    contact_name              text,
    contact_position          text,
    note                      text,
    status_id                 smallint not null references statuses (id),

    constraint job_processes_initiator_chk check (initiator in ('applicant', 'employer')),
    constraint job_processes_company_chk   check (btrim(company_name) <> ''),
    constraint job_processes_title_chk     check (btrim(vacancy_title) <> ''),
    constraint job_processes_url_chk       check (
        vacancy_url is null or vacancy_url ~ '^https?://[^[:space:]]+$'
    ),
    -- INV-02: поля, обязательные для отклика соискателя
    constraint job_processes_applicant_chk check (
        initiator <> 'applicant'
        or (vacancy_url is not null
            and vacancy_source_id is not null
            and apply_channel_id is not null
            and has_cover_letter is not null)
    ),
    -- INV-02, INV-03: поля входящего процесса
    constraint job_processes_employer_chk check (
        initiator <> 'employer'
        or (vacancy_source_id is null
            and apply_channel_id is null
            and has_cover_letter is null
            and communication_channel_id is not null
            and first_response_on is null)
    ),
    -- INV-05: вилка «на руки», рубли
    constraint job_processes_salary_from_chk  check (salary_from is null or salary_from > 0),
    constraint job_processes_salary_to_chk    check (salary_to is null or salary_to > 0),
    constraint job_processes_salary_range_chk check (
        salary_from is null or salary_to is null or salary_from <= salary_to
    ),
    -- INV-06 (часть, проверяемая базой): ответ не раньше начала процесса
    constraint job_processes_first_response_chk check (
        first_response_on is null or first_response_on >= started_on
    )
);


-- ---------------------------------------------------------------------
-- История статусов процесса
-- ---------------------------------------------------------------------

create table process_status_history (
    id                   bigint      generated always as identity primary key,
    process_id           bigint      not null references job_processes (id) on delete cascade,
    status_id            smallint    not null references statuses (id),
    stage_date           date        not null,
    recorded_at          timestamptz not null default now(),
    changed_by           text        not null,
    note                 text,
    rejection_reason_id  smallint references rejection_reasons (id),
    constraint process_status_history_changed_by_chk check (changed_by in ('applicant', 'system'))
);


-- ---------------------------------------------------------------------
-- Тестовые задания
-- ---------------------------------------------------------------------

create table test_assignments (
    id            bigint   generated always as identity primary key,
    process_id    bigint   not null references job_processes (id) on delete cascade,
    status_id     smallint not null references statuses (id),
    received_on   date     not null,
    due_on        date,
    submitted_on  date,
    result_note   text,
    constraint test_assignments_due_chk       check (due_on is null or due_on >= received_on),
    constraint test_assignments_submitted_chk check (submitted_on is null or submitted_on >= received_on)
);


-- ---------------------------------------------------------------------
-- Связи с навыками
-- ---------------------------------------------------------------------

create table process_skills (
    process_id  bigint  not null references job_processes (id) on delete cascade,
    skill_id    integer not null references skills (id),
    primary key (process_id, skill_id)
);

create table profile_skills (
    direction_id  smallint not null references directions (id),
    skill_id      integer  not null references skills (id),
    primary key (direction_id, skill_id)
);


-- ---------------------------------------------------------------------
-- Индексы (объёмы малы, набор минимален; обоснование в 02-physical-model.md)
-- ---------------------------------------------------------------------

-- Список процессов, сортировка по дате начала (US-04)
create index ix_job_processes_started_on
    on job_processes (started_on desc, id desc);

-- Фильтры по направлению и статусу (US-04, аналитика)
create index ix_job_processes_direction_status
    on job_processes (direction_id, status_id);

-- Поиск возможных дублей (US-02, D18)
create index ix_job_processes_company_title
    on job_processes (lower(btrim(company_name)), lower(btrim(vacancy_title)));

create index ix_job_processes_vacancy_url
    on job_processes (vacancy_url)
    where vacancy_url is not null;

-- Кандидаты на автозакрытие (US-11, D10)
create index ix_job_processes_autoclose
    on job_processes (started_on)
    where initiator = 'applicant' and first_response_on is null;

-- Последняя запись истории процесса (INV-10), история процесса (US-07)
create index ix_status_history_process_recorded
    on process_status_history (process_id, recorded_at, id);

-- Воронка: какие процессы достигли статуса (US-16)
create index ix_status_history_status_process
    on process_status_history (status_id, process_id);

-- Тестовые задания процесса и ближайшие сроки сдачи (US-10, US-13)
create index ix_test_assignments_process
    on test_assignments (process_id);

create index ix_test_assignments_due_open
    on test_assignments (due_on)
    where submitted_on is null and due_on is not null;

-- Обратный поиск по навыку (рейтинг навыков, US-21)
create index ix_process_skills_skill
    on process_skills (skill_id);

create index ix_profile_skills_skill
    on profile_skills (skill_id);


-- ---------------------------------------------------------------------
-- Комментарии к таблицам (словарь данных внутри базы)
-- ---------------------------------------------------------------------

comment on table directions             is 'Справочник: направления поиска (SA/BA, TW)';
comment on table vacancy_sources        is 'Справочник: источники вакансий (где найдена вакансия)';
comment on table channels               is 'Справочник: каналы отклика и общения; is_apply_channel = можно ли откликнуться этим каналом';
comment on table employer_types         is 'Справочник: типы работодателя';
comment on table employment_formats     is 'Справочник: форматы трудоустройства';
comment on table rejection_reasons      is 'Справочник: причины отказов';
comment on table statuses               is 'Справочник: статусы процесса (этапы воронки и итоги); kind, stage_order, is_required_stage нужны для расчёта воронки (SR11)';
comment on table skills                 is 'Справочник навыков; название уникально без учёта регистра';
comment on table job_processes          is 'Процесс: отклик соискателя (initiator = applicant) или входящий контакт работодателя (initiator = employer)';
comment on table process_status_history is 'История статусов процесса; каждая запись = один установленный статус с датой этапа';
comment on table test_assignments       is 'Тестовые задания по процессу';
comment on table process_skills         is 'Навыки вакансии (вводятся начиная с HR-интервью, D8)';
comment on table profile_skills         is 'Профиль навыков соискателя по направлениям (D3)';

comment on column job_processes.started_on        is 'Дата отклика (applicant) или дата первого контакта (employer)';
comment on column job_processes.salary_from       is 'Вилка «на руки», руб.; пересчёт в «на руки» выполняет соискатель (D15)';
comment on column job_processes.first_response_on is 'Дата первого содержательного ответа работодателя (D13)';
comment on column job_processes.status_id         is 'Текущий статус; поддерживается триггером по последней записи истории (INV-10)';
comment on column process_status_history.stage_date  is 'Дата этапа (прошедшего или запланированного) либо дата закрытия';
comment on column process_status_history.recorded_at is 'Момент создания записи; порядок записей: recorded_at, затем id';
