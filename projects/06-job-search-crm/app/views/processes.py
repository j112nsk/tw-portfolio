"""Страница «Процессы» (US-02, US-03): список процессов с фильтрами и поиском."""
from datetime import date

import streamlit as st

from app import data, formatting as fmt, ui

ALL = "Все"
STATE_OPTIONS = {ALL: None, "Открытые": "open", "Закрытые": "closed"}
INITIATOR_OPTIONS = {ALL: None, fmt.INITIATOR_LABELS["applicant"]: "applicant",
                     fmt.INITIATOR_LABELS["employer"]: "employer"}


def options(rows: list[dict]) -> dict[str, str]:
    """Название -> код для значений справочника."""
    return {row["name_ru"]: row["code"] for row in rows}


def pick(mapping: dict[str, str | None], label: str) -> str | None:
    """Код выбранного значения; «Все» означает «без фильтра»."""
    return mapping.get(label)


today = date.today()
col_title, col_btn = st.columns([0.8, 0.2], vertical_alignment="center")
with col_title:
    st.title("Процессы")
with col_btn:
    if st.button("➕ Создать процесс", type="primary", use_container_width=True):
        st.switch_page("views/process_new.py")

directions = options(data.get_reference("directions"))
statuses = options(data.get_reference("statuses"))
sources = {ALL: None, **options(data.get_reference("vacancy_sources"))}
apply_channels = {ALL: None, **options(data.get_apply_channels())}
comm_channels = {ALL: None, **options(data.get_reference("channels"))}
employer_types = {ALL: None, **options(data.get_reference("employer_types"))}
formats = {ALL: None, **options(data.get_reference("employment_formats"))}

with st.expander("Фильтры", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        chosen_directions = st.multiselect("Направление", list(directions))
        chosen_statuses = st.multiselect("Статус", list(statuses))
        state_label = st.radio("Состояние", list(STATE_OPTIONS), horizontal=True)
    with col2:
        initiator_label = st.selectbox("Кто начал", list(INITIATOR_OPTIONS))
        source_label = st.selectbox("Источник вакансии", list(sources))
        apply_label = st.selectbox("Канал отклика", list(apply_channels))
    with col3:
        comm_label = st.selectbox("Канал общения", list(comm_channels))
        employer_label = st.selectbox("Тип работодателя", list(employer_types))
        format_label = st.selectbox("Формат трудоустройства", list(formats))
    col4, col5, col6 = st.columns(3)
    with col4:
        date_from = st.date_input("Дата начала процесса: с", value=None, format="DD.MM.YYYY")
    with col5:
        date_to = st.date_input("Дата начала процесса: по", value=None, format="DD.MM.YYYY")
    with col6:
        search = st.text_input("Поиск по компании, вакансии и ссылке")

filters = {
    "directions": [directions[name] for name in chosen_directions],
    "statuses": [statuses[name] for name in chosen_statuses],
    "state": STATE_OPTIONS[state_label],
    "initiator": INITIATOR_OPTIONS[initiator_label],
    "source": pick(sources, source_label),
    "apply_channel": pick(apply_channels, apply_label),
    "comm_channel": pick(comm_channels, comm_label),
    "employer_type": pick(employer_types, employer_label),
    "employment_format": pick(formats, format_label),
    "date_from": date_from,
    "date_to": date_to,
    "search": search,
}

rows = data.list_processes(filters, today)
total = data.count_processes()
st.caption(f"Показано {len(rows)} из {total}")

selected_id = None
if not rows:
    st.info("Процессов нет.")
else:
    table = [{"Компания": r["company_name"], "Вакансия": r["vacancy_title"], "Ссылка": r["vacancy_url"],
              "Направление": fmt.direction_label(r["direction_code"]), "Статус": r["status_name"],
              "Ближайший этап": fmt.format_next_stage(r["next_date"], r["next_name"]),
              "Последняя запись": r["last_record_date"], "Кто начал": fmt.initiator_label(r["initiator"])}
             for r in rows]
    event = st.dataframe(
        table, key="processes_table", hide_index=True, width="stretch",
        column_config={"Ссылка": st.column_config.LinkColumn(display_text="Открыть"),
                       "Последняя запись": st.column_config.DateColumn(format="DD.MM.YYYY")},
        on_select="rerun", selection_mode="single-row")
    chosen = event["selection"]["rows"]
    if chosen:
        selected_id = rows[chosen[0]]["id"]

ui.open_card_button(selected_id)
