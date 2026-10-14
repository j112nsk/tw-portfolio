"""Страница «Карточка процесса»: основные поля, история этапов, тестовые задания, навыки.

На этом шаге карточка только показывает данные; действия (назначить этап, закрыть, тестовое,
навыки, правка) добавляются следующим шагом.
"""
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

st.subheader("История этапов")
st.dataframe(
    [{"Дата этапа": row["stage_date"], "Статус": row["status"], "Причина отказа": row["reason"],
      "Комментарий": row["note"]} for row in card["history"]],
    hide_index=True, width="stretch",
    column_config={"Дата этапа": st.column_config.DateColumn(format="DD.MM.YYYY")})

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

st.info("Действия над процессом (назначить этап, закрыть, добавить тестовое, навыки, правка данных) "
        "появятся на следующем шаге.")
