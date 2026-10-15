"""Страница «Карточка процесса»: поля, действия, история этапов, тестовые задания, навыки.

Действия:
  * «Назначить этап» (US-04) — с подтверждением нетипичных переходов.
  * «Закрыть процесс» (US-06) — с выбором итога и причины отказа (SR9).
Остальные действия (правка полей, удаление, тестовые, навыки) — следующий заход.
"""
from datetime import date

import pandas as pd
import streamlit as st

from app import data, formatting as fmt

st.page_link("views/processes.py", label="К списку процессов", icon="📋")

process_id = st.session_state.get("process_id")
if process_id is None:
    st.info("Выберите процесс на странице «Процессы» или «Напоминания».")
    st.stop()

card = data.get_process_card(process_id)
if card is None:
    st.error("Процесс не найден: возможно, он был удалён.")
    st.stop()

process = card["process"]
st.title(f"{process['company_name']}: {process['vacancy_title']}")
st.markdown(f"**Статус:** {process['status']} · **Направление:** {process['direction']} · "
            f"**Кто начал:** {fmt.initiator_label(process['initiator'])}")

left, right = st.columns(2)
with left:
    st.subheader("Основное")
    if process["vacancy_url"]:
        st.markdown(f"**Ссылка на вакансию:** [{process['vacancy_url']}]({process['vacancy_url']})")
    else:
        st.markdown("**Ссылка на вакансию:** не указана")
    if process["initiator"] == "applicant":
        st.markdown(f"**Источник вакансии:** {process['source']}")
        st.markdown(f"**Канал отклика:** {process['apply_channel']}")
    st.markdown(f"**Канал общения:** {process['comm_channel']}")
with right:
    st.subheader("Условия и контакт")
    st.markdown(f"**Тип работодателя:** {process['employer_type'] or 'не указан'}")
    st.markdown(f"**Формат трудоустройства:** {process['employment_format'] or 'не указан'}")
    st.markdown(f"**Вилка:** {fmt.format_salary(process['salary_from'], process['salary_to'])}")
    contact = ", ".join(part for part in (process["contact_name"], process["contact_position"]) if part)
    st.markdown(f"**Контакт:** {contact or 'не указан'}")
if process["note"]:
    st.markdown(f"**Комментарий:** {process['note']}")

is_open = process["status_kind"] == "stage"

# ---------------------------------------------------------------- действия

st.subheader("Действия")

stages = data.get_statuses_by_kind("stage")
outcomes = data.get_statuses_by_kind("outcome")
rejection_reasons = data.get_reference("rejection_reasons")

PENDING_STAGE   = "pending_stage_change"
PENDING_CLOSE   = "pending_close_change"
PENDING_WARNS   = "pending_warnings"


def _clear_pending() -> None:
    for key in (PENDING_STAGE, PENDING_CLOSE, PENDING_WARNS):
        st.session_state.pop(key, None)


def _show_pending_and_confirm(save_callable) -> None:
    """Показывает предупреждения и кнопки «Подтвердить / Отмена» для сохранения."""
    st.warning("Нетипичный переход — требуется подтверждение:")
    for _code, text in st.session_state[PENDING_WARNS]:
        st.write(f"— {text}")
    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button("Подтвердить", type="primary", key="btn_confirm"):
            try:
                save_callable()
            except ValueError as error:
                st.error(str(error))
            else:
                _clear_pending()
                st.success("Сохранено.")
                st.rerun()
    with col_cancel:
        if st.button("Отмена", key="btn_cancel"):
            _clear_pending()
            st.rerun()


tab_stage, tab_close = st.tabs(["Назначить этап", "Закрыть процесс"])

with tab_stage:
    if not is_open:
        st.caption("Процесс закрыт. Установка этапа вернёт его в работу с предупреждением.")
    stage_name = st.selectbox(
        "Этап", options=[s["name_ru"] for s in stages], key="card_stage_name")
    stage_code = next(s["code"] for s in stages if s["name_ru"] == stage_name)
    stage_date = st.date_input(
        "Дата этапа", value=date.today(), format="DD.MM.YYYY", key="card_stage_date")
    stage_note = st.text_input("Комментарий (необязательно)", key="card_stage_note")

    if st.button("Сохранить этап", type="primary", key="card_stage_save"):
        try:
            warnings = data.update_process_status(
                process_id, stage_code, stage_date, stage_note or None, conn=None)
        except ValueError as error:
            # Возможные случаи: нетипичный переход (надо подтвердить) или иная ошибка
            if "требует подтверждения" in str(error):
                st.session_state[PENDING_WARNS] = data.check_atypical_transition(
                    process_id, stage_code)
                st.session_state[PENDING_STAGE] = (stage_code, stage_date, stage_note)
                st.rerun()
            else:
                st.error(str(error))
        else:
            st.success("Этап сохранён.")
            st.rerun()

    if PENDING_STAGE in st.session_state:
        def _save_stage():
            code, dt, note = st.session_state[PENDING_STAGE]
            data.update_process_status(process_id, code, dt, note or None,
                                       confirm_atypical=True)
        _show_pending_and_confirm(_save_stage)

with tab_close:
    if not is_open:
        st.caption("Процесс уже закрыт. Закрытие повторно — тоже нетипичный переход.")
    outcome_name = st.selectbox(
        "Итог", options=[o["name_ru"] for o in outcomes], key="card_outcome_name")
    outcome_code = next(o["code"] for o in outcomes if o["name_ru"] == outcome_name)
    close_date = st.date_input(
        "Дата закрытия", value=date.today(), format="DD.MM.YYYY", key="card_close_date")

    reason_code: str | None = None
    if outcome_code in ("REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME"):
        reason_name = st.selectbox(
            "Причина отказа", options=["—"] + [r["name_ru"] for r in rejection_reasons],
            key="card_close_reason")
        if reason_name != "—":
            reason_code = next(r["code"] for r in rejection_reasons if r["name_ru"] == reason_name)
        st.caption("Причина обязательна, если в истории есть HR-интервью или тестовое (SR9).")

    if st.button("Закрыть процесс", type="primary", key="card_close_save"):
        try:
            data.close_process(
                process_id, outcome_code, close_date,
                rejection_reason_code=reason_code, conn=None)
        except ValueError as error:
            if "требует подтверждения" in str(error):
                st.session_state[PENDING_WARNS] = data.check_atypical_transition(
                    process_id, outcome_code)
                st.session_state[PENDING_CLOSE] = (outcome_code, close_date, reason_code)
                st.rerun()
            else:
                st.error(str(error))
        else:
            st.success("Процесс закрыт.")
            st.rerun()

    if PENDING_CLOSE in st.session_state:
        def _save_close():
            code, dt, reason = st.session_state[PENDING_CLOSE]
            data.close_process(process_id, code, dt, rejection_reason_code=reason,
                               confirm_atypical=True)
        _show_pending_and_confirm(_save_close)

# ---------------------------------------------------------------- история, тесты, навыки

st.subheader("История этапов")
st.caption("Сверху — самые свежие записи. Зелёный фон — этапы, красный — итоги.")

# Список «видов» статусов идёт параллельно строкам: row.name — целочисленный индекс
# (0, 1, 2, …), по нему достаём нужный вид. Индекс оставлен обычным: pandas требует
# уникальный индекс для Styler.apply, а status_kind уникальным не является.
history_kinds = [row["status_kind"] for row in card["history"]]

history_df = pd.DataFrame([
    {"Дата этапа": fmt.format_date(row["stage_date"]),
     "Статус": row["status"],
     "Причина отказа": row["reason"] or "",
     "Комментарий": row["note"] or ""}
    for row in card["history"]
])


def _highlight_history_row(row):
    """Полупрозрачная тонировка строки: зелёная для этапов, красная для итогов.

    rgba с прозрачностью работает и в тёмной, и в светлой теме Streamlit: цвет читается,
    а системный цвет текста остаётся контрастным.
    """
    color = ("rgba(76, 175, 80, 0.22)"   if history_kinds[row.name] == "stage"
             else "rgba(244, 67, 54, 0.22)")
    return [f"background-color: {color}"] * len(row)


st.dataframe(history_df.style.apply(_highlight_history_row, axis=1),
             hide_index=True, width="stretch")

st.subheader("Тестовые задания")
if card["tests"]:
    st.dataframe(
        [{"Получено": row["received_on"], "Статус при получении": row["status_at_receipt"],
          "Срок сдачи": row["due_on"], "Сдано": row["submitted_on"], "Результат": row["result_note"]}
         for row in card["tests"]],
        hide_index=True, width="stretch",
        column_config={"Получено": st.column_config.DateColumn(format="DD.MM.YYYY"),
                       "Срок сдачи": st.column_config.DateColumn(format="DD.MM.YYYY"),
                       "Сдано": st.column_config.DateColumn(format="DD.MM.YYYY")})
else:
    st.caption("Тестовых заданий нет.")

st.subheader("Навыки вакансии")
if card["skills"]:
    st.write(", ".join(card["skills"]))
else:
    st.caption("Навыки не указаны.")