-- =====================================================================
-- 002_seed_reference_data.sql
-- Job Search CRM: начальные значения справочников (US-14).
-- Приложение и запросы обращаются к значениям по полю code, а не по id.
-- =====================================================================

insert into directions (code, name_ru, sort_order) values
    ('SA_BA', 'Системный / бизнес-аналитик', 1),
    ('TW',    'Технический писатель',        2);

insert into vacancy_sources (code, name_ru, sort_order) values
    ('HH_RU',            'hh.ru',            1),
    ('TELEGRAM_CHANNEL', 'Telegram-канал',   2),
    ('COMPANY_SITE',     'Сайт компании',    3),
    ('OTHER',            'Другое',           4);

insert into channels (code, name_ru, sort_order, is_apply_channel) values
    ('HH_RU',    'hh.ru',    1, true),
    ('TELEGRAM', 'Telegram', 2, true),
    ('EMAIL',    'Почта',    3, true),
    ('PHONE',    'Телефон',  4, false);

insert into employer_types (code, name_ru, sort_order) values
    ('DIRECT',          'Прямой работодатель', 1),
    ('OUTSTAFF',        'Аутстафф',            2),
    ('STAFFING_AGENCY', 'Кадровое агентство',  3);

insert into employment_formats (code, name_ru, sort_order) values
    ('LABOR_CONTRACT',  'ТК',          1),
    ('CIVIL_CONTRACT',  'ГПХ (ИП/СЗ)', 2);

insert into rejection_reasons (code, name_ru, sort_order) values
    ('NO_REASON',             'Без причины',               1),
    ('EXPERIENCE_MISMATCH',   'Не подошёл опыт',           2),
    ('OTHER_CANDIDATE_CHOSEN','Выбрали другого',           3),
    ('CONDITIONS_MISMATCH',   'Условия не подошли мне',    4),
    ('OTHER',                 'Другое',                    5);

insert into statuses (code, name_ru, sort_order, kind, stage_order, is_required_stage) values
    ('APPLIED',              'Отклик',                    1,  'stage',   1,    true),
    ('HR_INTERVIEW',         'HR-интервью',               2,  'stage',   2,    true),
    ('TECH_INTERVIEW',       'Техническое собеседование', 3,  'stage',   3,    true),
    ('TEAM_MEETING',         'Знакомство с командой',     4,  'stage',   4,    false),
    ('SECURITY_CHECK',       'СБ',                        5,  'stage',   5,    false),
    ('OFFER',                'Оффер',                     6,  'stage',   6,    true),
    ('OFFER_ACCEPTED',       'Оффер принят',              7,  'outcome', null, null),
    ('OFFER_DECLINED',       'Оффер отклонён мной',       8,  'outcome', null, null),
    ('REJECTED_BY_EMPLOYER', 'Отказ работодателя',        9,  'outcome', null, null),
    ('WITHDRAWN_BY_ME',      'Мой отказ',                 10, 'outcome', null, null),
    ('NO_RESPONSE',          'Нет ответа',                11, 'outcome', null, null);
