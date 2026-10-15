"""Страница «Создать процесс» (US-01).

Одна форма для обоих инициаторов: applicant (я откликнулся) и employer (работодатель
написал первым). Значения по умолчанию берутся из последнего созданного процесса
(US-01, критерий 2): направление и канал общения — из последнего процесса, источник
и канал отклика — из последнего процесса, начатого откликом.

Все данные при ошибке сохраняются в виджетах: Streamlit хранит их в session_state
по стабильному ключу, поэтому пользователю не нужно вводить заново.
"""
from datetime import date

import streamlit as st

from app import data

st.title("➕ Создать процесс")
st.caption(
    "Форма для процессов, дошедших до интервью или тестового, а также для входящих "
    "контактов, по которым назначен следующий этап (D23)."
)


# ---------------------------------------------------------------- справочники

directions = data.get_reference("directions")
vacancy_sources = data.get_reference("vacancy_sources")
apply_channels = data.get_apply_channels()
all_channels = data.get_reference("channels")
employer_types = data.get_reference("employer_types")
employment_formats = data.get_reference("employment_formats")
stages = data.get_initial_stages()
defaults = data.get_last_process_defaults()


def index_of(rows: list[dict], code: str | None, default: int = 0) -> int:
    """Индекс строки с заданным code; default, если code не найден или None."""
    if code is None:
        return default
    for i, row in enumerate(rows):
        if row["code"] == code:
            return i
    return default


# ---------------------------------------------------------------- основное

st.subheader("Основное")

initiator_label = st.radio(
    "Кто начал",
    options=["Я откликнулся", "Работодатель написал первым"],
    horizontal=True, key="np_initiator")
initiator = "applicant" if initiator_label == "Я откликнулся" else "employer"

direction_name = st.selectbox(
    "Направление", options=[d["name_ru"] for d in directions],
    index=index_of(directions, defaults["direction_code"]), key="np_direction")
direction_code = next(d["code"] for d in directions if d["name_ru"] == direction_name)

company_name = st.text_input("Компания", key="np_company")
vacancy_title = st.text_input("Название вакансии", key="np_title")
vacancy_url = st.text_input(
    "Ссылка на вакансию",
    key="np_url",
    help="Необязательно. Если указана, должна начинаться с http:// или https://")


# ---------------------------------------------------------------- этап

st.subheader("Начальный этап")

stage_name = st.selectbox(
    "Этап", options=[s["name_ru"] for s in stages],
    index=index_of(stages, "HR_INTERVIEW"), key="np_stage")
stage_code = next(s["code"] for s in stages if s["name_ru"] == stage_name)

stage_date = st.date_input(
    "Дата этапа (или дата выдачи тестового)", value=date.today(),
    format="DD.MM.YYYY", key="np_stage_date")

test_due_on: date | None = None
if stage_code == "APPLIED":
    st.caption("Этап «Отклик» используется, когда первым выдано тестовое задание "
               "(D25). При сохранении тестовое будет создано автоматически.")
    test_due_on = st.date_input(
        "Срок сдачи тестового", value=None, format="DD.MM.YYYY", key="np_test_due")


# ---------------------------------------------------------------- каналы

st.subheader("Источники и каналы")

source_code: str | None = None
apply_code: str | None = None

if initiator == "applicant":
    source_name = st.selectbox(
        "Источник вакансии", options=[s["name_ru"] for s in vacancy_sources],
        index=index_of(vacancy_sources, defaults["vacancy_source_code"]),
        key="np_source")
    source_code = next(s["code"] for s in vacancy_sources if s["name_ru"] == source_name)

    apply_name = st.selectbox(
        "Канал отклика", options=[c["name_ru"] for c in apply_channels],
        index=index_of(apply_channels, defaults["apply_channel_code"]),
        key="np_apply")
    apply_code = next(c["code"] for c in apply_channels if c["name_ru"] == apply_name)
else:
    st.caption("Для входящего процесса источник вакансии и канал отклика не заполняются (D11).")

comm_name = st.selectbox(
    "Канал общения", options=[c["name_ru"] for c in all_channels],
    index=index_of(all_channels, defaults["communication_channel_code"]),
    key="np_comm")
comm_code = next(c["code"] for c in all_channels if c["name_ru"] == comm_name)


# ---------------------------------------------------------------- дополнительно

with st.expander("Дополнительные поля (необязательно)"):
    et_name = st.selectbox(
        "Тип работодателя", options=["—"] + [e["name_ru"] for e in employer_types],
        key="np_et")
    et_code = None if et_name == "—" else next(
        e["code"] for e in employer_types if e["name_ru"] == et_name)

    ef_name = st.selectbox(
        "Формат трудоустройства",
        options=["—"] + [e["name_ru"] for e in employment_formats], key="np_ef")
    ef_code = None if ef_name == "—" else next(
        e["code"] for e in employment_formats if e["name_ru"] == ef_name)

    col_from, col_to = st.columns(2)
    with col_from:
        salary_from_raw = st.number_input(
            "Вилка «от», ₽ «на руки»", min_value=0, step=1000, value=0, key="np_sf")
    with col_to:
        salary_to_raw = st.number_input(
            "Вилка «до», ₽ «на руки»", min_value=0, step=1000, value=0, key="np_st")

    contact_name = st.text_input("Контакт: имя", key="np_cn")
    contact_position = st.text_input("Контакт: должность", key="np_cp")
    note = st.text_area("Комментарий", key="np_note")


# ---------------------------------------------------------------- сохранение

if st.button("Сохранить", type="primary", key="np_save"):
    salary_from = int(salary_from_raw) if salary_from_raw > 0 else None
    salary_to = int(salary_to_raw) if salary_to_raw > 0 else None

    try:
        pid = data.create_process(
            direction_code=direction_code,
            initiator=initiator,
            company_name=company_name,
            vacancy_title=vacancy_title,
            initial_status_code=stage_code,
            initial_stage_date=stage_date,
            communication_channel_code=comm_code,
            vacancy_source_code=source_code,
            apply_channel_code=apply_code,
            vacancy_url=vacancy_url.strip() or None,
            employer_type_code=et_code,
            employment_format_code=ef_code,
            salary_from=salary_from,
            salary_to=salary_to,
            contact_name=contact_name.strip() or None,
            contact_position=contact_position.strip() or None,
            note=note.strip() or None,
            test_due_on=test_due_on,
        )
    except ValueError as error:
        st.error(str(error))
    else:
        st.session_state["process_id"] = pid
        st.switch_page("views/process_card.py")