-- =====================================================================
-- 005_test_assignment_as_stage.sql
-- ADR-002, D32: тестовое задание становится обычным этапом отбора.
--   * Добавляется статус TEST_ASSIGNMENT (stage, порядок 2, не обязательный,
--     вне воронки).
--   * Удаляется статус APPLIED («Отклик»).
--   * Удаляется таблица test_assignments.
--   * Записи истории со статусом APPLIED переводятся в TEST_ASSIGNMENT
--     (сохраняются дата этапа, момент записи, комментарий).
--   * У job_processes.status_id, где был APPLIED, — тоже становится
--     TEST_ASSIGNMENT.
-- Порядок важен: сначала переводим записи и статусы процессов,
-- потом удаляем таблицу test_assignments (на statuses есть FK от неё),
-- потом удаляем APPLIED, потом сдвигаем порядки HR и TEST.
-- =====================================================================

-- 1. Вставляем новый статус с временными значениями sort_order и stage_order,
--    чтобы не конфликтовать с существующим уникальным stage_order.
insert into statuses (code, name_ru, sort_order, kind, stage_order, is_required_stage, in_funnel)
values ('TEST_ASSIGNMENT', 'Тестовое задание', 100, 'stage', 100, false, false);

-- 2. Записи истории: APPLIED -> TEST_ASSIGNMENT
update process_status_history
   set status_id = (select id from statuses where code = 'TEST_ASSIGNMENT')
 where status_id = (select id from statuses where code = 'APPLIED');

-- 3. Текущий статус процессов: APPLIED -> TEST_ASSIGNMENT
update job_processes
   set status_id = (select id from statuses where code = 'TEST_ASSIGNMENT')
 where status_id = (select id from statuses where code = 'APPLIED');

-- 4. Удаляем таблицу test_assignments (FK на statuses пропадает)
drop table if exists test_assignments;

-- 5. Удаляем APPLIED
delete from statuses where code = 'APPLIED';

-- 6. Сдвигаем финальные порядки: HR становится 1, TEST становится 2
update statuses set sort_order = 1, stage_order = 1 where code = 'HR_INTERVIEW';
update statuses set sort_order = 2, stage_order = 2 where code = 'TEST_ASSIGNMENT';