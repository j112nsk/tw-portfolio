"""Страница «Навыки» — профиль навыков соискателя по направлениям (US-11, D3).

Профиль ведётся отдельно для каждого направления (SA/BA, TW) и не пересекается с навыками
вакансий: те вводятся в карточке процесса (там же и подсказки по направлению).
"""
import streamlit as st

from app import data, formatting as fmt

st.title("🧩 Навыки")
st.caption("Профиль навыков соискателя ведётся отдельно для каждого направления (D3). "
           "Эти навыки сравниваются с навыками вакансий в аналитике (Q6).")

directions = data.get_reference("directions")

if not directions:
    st.info("Справочник направлений пуст.")
    st.stop()

# ---------------------------------------------------------------- сводка по всем направлениям

profiles = data.get_all_profile_skills()

st.subheader("Сводка")
summary_cols = st.columns(len(directions))
for col, direction in zip(summary_cols, directions):
    code = direction["code"]
    skills = profiles.get(code, [])
    with col:
        st.markdown(f"**{direction['name_ru']}**")
        st.metric("Навыков в профиле", len(skills))
        if skills:
            st.caption(", ".join(skills))
        else:
            st.caption("Профиль пуст.")


# ---------------------------------------------------------------- редактор профиля

st.subheader("Редактор профиля")

direction_names = [d["name_ru"] for d in directions]
chosen_name = st.selectbox("Направление", options=direction_names, key="skills_direction")
chosen_code = next(d["code"] for d in directions if d["name_ru"] == chosen_name)

current_skills = data.get_direction_profile_skills(chosen_code)

# Собираем множество навыков, которые встречались у процессов этого направления:
# они полезны как подсказки — и как «пробелы», которые стоит добавить в профиль.
direction_suggestions = data.get_direction_skill_suggestions(chosen_code)
all_options = sorted({*current_skills, *direction_suggestions}, key=str.lower)

selected = st.multiselect(
    "Навыки в профиле",
    options=all_options,
    default=current_skills,
    accept_new_options=True,
    key=f"skills_profile_select_{chosen_code}",
    help="Выберите из подсказок или введите новые. Несколько новых — через запятую. "
         "Регистр и пробелы по краям не важны: повторяющиеся значения схлопываются (INV-14).",
)

col_save, col_clear = st.columns([0.5, 0.5])
with col_save:
    if st.button("Сохранить профиль", type="primary", key=f"skills_profile_save_{chosen_code}"):
        try:
            saved = data.set_profile_skills(chosen_code, selected)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Профиль сохранён: {len(saved)} навыков.")
            st.rerun()
with col_clear:
    confirm_clear = st.checkbox(
        "Подтверждаю очистку", key=f"skills_profile_clear_confirm_{chosen_code}")
    if st.button("Очистить профиль", disabled=not confirm_clear,
                 key=f"skills_profile_clear_{chosen_code}"):
        try:
            data.set_profile_skills(chosen_code, [])
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Профиль очищен.")
            st.rerun()


# ---------------------------------------------------------------- пробелы в профиле

st.subheader("Пробелы в профиле")

# Навыки, которые встречались у процессов направления, но не входят в профиль (Q6):
# это потенциальные кандидаты на добавление.
missing = sorted(set(direction_suggestions) - set(current_skills), key=str.lower)

if missing:
    st.markdown(f"Встречались в вакансиях **{chosen_name}**, но не в профиле "
                f"({len(missing)}):")
    st.write(", ".join(missing))
    st.caption("Список строится по процессам направления, у которых введены навыки. "
               "В рейтинг Q5/Q6 попадут только процессы, дошедшие до HR-интервью и далее (D8).")
else:
    st.caption("Все встречавшиеся навыки этого направления уже в профиле "
               "(или у процессов этого направления навыки ещё не вводились).")