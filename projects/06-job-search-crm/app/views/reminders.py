"""Страница «Напоминания» (US-08, US-09): этапы на ближайшие дни и процессы без следующего шага.

Страница только читает данные: ничего не закрывается и не меняется без действия пользователя (D24, NFR-07).
"""
from datetime import date

import streamlit as st

from app import data, formatting as fmt, ui

GROUPS = [
    ("today_tomorrow", "Сегодня и завтра", "Нет событий."),
    ("next_7_days", "В ближайшие 7 дней", "Нет событий."),
    ("no_planned_stage", "Нет запланированного этапа", "Нет процессов."),
]

today = date.today()
col_title, col_btn = st.columns([0.8, 0.2], vertical_alignment="center")
with col_title:
    st.title("Напоминания")
with col_btn:
    if st.button("➕ Создать процесс", type="primary", use_container_width=True):
        st.switch_page("views/process_new.py")
st.caption(f"Сегодня {fmt.format_date(today)}. Выберите строку, чтобы открыть карточку процесса.")

rows = data.get_reminders(today)
selected_id = None

for code, title, empty_text in GROUPS:
    group_rows = [row for row in rows if row["group_code"] == code]
    st.subheader(f"{title} ({len(group_rows)})")
    if not group_rows:
        st.caption(empty_text)
        continue

    if code == "no_planned_stage":
        table = [{"Компания": r["company_name"], "Вакансия": r["vacancy_title"],
                  "Направление": fmt.direction_label(r["direction"]),
                  "Дата последнего этапа": r["event_date"],
                  "Дней без этапа": r["days_since_last_stage"]} for r in group_rows]
        config = {"Дата последнего этапа": st.column_config.DateColumn(format="DD.MM.YYYY")}
    else:
        table = [{"Дата": r["event_date"], "Компания": r["company_name"], "Вакансия": r["vacancy_title"],
                  "Событие": r["event_name"], "Направление": fmt.direction_label(r["direction"])}
                 for r in group_rows]
        config = {"Дата": st.column_config.DateColumn(format="DD.MM.YYYY")}

    event = st.dataframe(table, key=f"reminders_{code}", hide_index=True, width="stretch",
                         column_config=config, on_select="rerun", selection_mode="single-row")
    chosen = event["selection"]["rows"]
    if chosen:
        selected_id = group_rows[chosen[0]]["process_id"]

ui.open_card_button(selected_id)
