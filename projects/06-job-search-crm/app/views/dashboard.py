"""Дашборд: аналитика воронки и поиска (Q1–Q9, Q12, Q13).

Общие правила (US-12…US-18):
  * каждый показатель сопровождается размером выборки N;
  * при N меньше 10 показывается пометка «малая выборка» (риск R2);
  * доли считаются среди процессов в системе (риск R15) — отклики без этапа не фиксируются;
  * Q5–Q7 отражают только процессы, дошедшие до интервью (риск R8);
  * Q5–Q7, Q18: вилки введены «на руки» после самостоятельного пересчёта (риск R14).

Данные берутся напрямую из SQL-запросов db/queries/; дашборд ничего не считает сам.
"""
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from app import data

st.title("📊 Дашборд")
st.caption("Аналитика строится по процессам в системе (ADR-001). Доли считаются среди "
           "уже попавших в систему процессов и не отражают результативность откликов "
           "в целом (риск R15).")


# ---------------------------------------------------------------- фильтры

with st.expander("Фильтры", expanded=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        period_label = st.selectbox(
            "Период (по дате начала процесса)",
            ["Всё время", "Последние 30 дней", "Последние 90 дней", "Последние 365 дней"],
            key="db_period")
    with col2:
        initiator_label = st.selectbox(
            "Инициатор", ["Все", "Я откликнулся", "Работодатель написал первым"],
            key="db_initiator")
    with col3:
        source_rows = data.get_reference("vacancy_sources")
        source_label = st.selectbox(
            "Источник вакансии", ["Все"] + [r["name_ru"] for r in source_rows],
            key="db_source")
    col4, col5, col6 = st.columns(3)
    with col4:
        apply_rows = data.get_apply_channels()
        apply_label = st.selectbox(
            "Канал отклика", ["Все"] + [r["name_ru"] for r in apply_rows],
            key="db_apply")
    with col5:
        et_rows = data.get_reference("employer_types")
        et_label = st.selectbox(
            "Тип работодателя", ["Все"] + [r["name_ru"] for r in et_rows],
            key="db_et")
    with col6:
        ef_rows = data.get_reference("employment_formats")
        ef_label = st.selectbox(
            "Формат трудоустройства", ["Все"] + [r["name_ru"] for r in ef_rows],
            key="db_ef")

today = date.today()
date_from: date | None = None
if period_label == "Последние 30 дней":
    date_from = today - timedelta(days=30)
elif period_label == "Последние 90 дней":
    date_from = today - timedelta(days=90)
elif period_label == "Последние 365 дней":
    date_from = today - timedelta(days=365)


def _code_or_none(rows: list[dict], label: str) -> str | None:
    if label == "Все":
        return None
    return next(r["code"] for r in rows if r["name_ru"] == label)


params = {
    "today": today,
    "initiator": {"Все": None, "Я откликнулся": "applicant",
                  "Работодатель написал первым": "employer"}[initiator_label],
    "date_from": date_from,
    "date_to": today,
    "source": _code_or_none(source_rows, source_label),
    "apply_channel": _code_or_none(apply_rows, apply_label),
    "employer_type": _code_or_none(et_rows, et_label),
    "employment_format": _code_or_none(ef_rows, ef_label),
}


def _small_n(n: int) -> str:
    return " (малая выборка)" if n < 10 else ""


def _direction_label(code: str) -> str:
    return {"SA_BA": "Системный / бизнес-аналитик",
            "TW": "Технический писатель",
            "ALL": "Все направления"}.get(code, code)


# ---------------------------------------------------------------- Q1: воронка и конверсия (US-12)

st.subheader("Воронка и конверсия по направлениям")
st.caption("Q1. Считается по истории этапов (SR11); статус «Отклик» в воронку не входит "
           "(D25, отдельной строкой «только тестовое»).")

funnel_rows = data.run_analysis_query("02-funnel.sql", params)

if not funnel_rows:
    st.info("Нет данных за выбранный период.")
else:
    STAGE_NAMES = ["HR-интервью", "Техническое собеседование",
                   "Знакомство с командой", "СБ", "Оффер"]
    STAGE_COLORS = ["#4caf50", "#2196f3", "#9c27b0", "#ff9800", "#fbc02d"]

    cols = st.columns(len(funnel_rows))
    for col, row in zip(cols, funnel_rows):
        with col:
            st.markdown(f"**{_direction_label(row['scope'])}**")
            st.caption(f"Процессов: {row['n_total']}{_small_n(row['n_total'])}")

            chart_df = pd.DataFrame({
                "Этап": STAGE_NAMES,
                "N": [row["n_hr"], row["n_tech"], row["n_team"],
                      row["n_security"], row["n_offer"]],
            })
            pie = (
                alt.Chart(chart_df)
                .mark_arc(innerRadius=58, outerRadius=105)
                .encode(
                    theta=alt.Theta("N:Q"),
                    color=alt.Color(
                        "Этап:N",
                        scale=alt.Scale(domain=STAGE_NAMES, range=STAGE_COLORS),
                        legend=alt.Legend(orient="bottom", direction="horizontal",
                                          columns=2, title=None, labelLimit=200,
                                          symbolSize=120),
                    ),
                    tooltip=["Этап", alt.Tooltip("N:Q", title="Процессов")],
                )
                .properties(width=420, height=400, padding={"top": 4, "bottom": 4, "left": 4, "right": 4})
                .configure_view(stroke=None)
            )
            st.altair_chart(pie, use_container_width=False)

            conv_hr_tech = f"{row['pct_tech_of_hr']}%" if row['pct_tech_of_hr'] is not None else "—"
            conv_tech_offer = f"{row['pct_offer_of_tech']}%" if row['pct_offer_of_tech'] is not None else "—"
            conv_hr_offer = f"{row['pct_offer_of_hr']}%" if row['pct_offer_of_hr'] is not None else "—"
            st.markdown(
                f"<div style='font-size: 0.9em; line-height: 1.6'>"
                f"HR → тех.: <b>{conv_hr_tech}</b><br>"
                f"Тех. → оффер: <b>{conv_tech_offer}</b><br>"
                f"HR → оффер: <b>{conv_hr_offer}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------- Q3, Q9: источники и каналы (US-14)

st.subheader("Источники вакансий и каналы отклика")
st.caption("Q3, Q9. Считаются только процессы, начатые откликом (D30): у входящих нет "
           "источника и канала отклика. Доли считаются среди процессов в системе (R15).")

source_rows_data = data.run_analysis_query("04-sources-and-channels.sql", params)
if not source_rows_data:
    st.info("Нет данных.")
else:
    by_direction: dict[str, list[dict]] = {}
    for r in source_rows_data:
        by_direction.setdefault(r["direction"], []).append(r)
    for direction, rows in by_direction.items():
        st.markdown(f"**{_direction_label(direction)}**")
        df = pd.DataFrame([{
            "Измерение": "Источник" if r["dimension"] == "SOURCE" else "Канал отклика",
            "Значение": r["value_name"],
            "Процессов": r["n_processes"],
            "Доля, %": r["share_pct"],
            "Дошли до тех., N": r["n_tech"],
            "Дошли до тех., %": r["pct_tech"],
            "Дошли до оффера, N": r["n_offer"],
            "Дошли до оффера, %": r["pct_offer"],
        } for r in rows])
        st.dataframe(df, hide_index=True, width="stretch")
        incoming = rows[0]["incoming_excluded"] if rows else 0
        if incoming:
            st.caption(f"Входящих процессов направления, не входящих в расчёт: {incoming}.")


# ---------------------------------------------------------------- Q2: дни между этапами (US-13)

st.subheader("Дни между этапами")
st.caption("Q2. Календарные дни между первыми записями этапов (SR12, D29). "
           "Пары с отрицательной разницей исключаются.")

days_rows = data.run_analysis_query("03-days-between-stages.sql", params)
if not days_rows:
    st.info("Нет данных.")
else:
    pair_labels = {"HR_TO_TECH": "HR-интервью → техническое",
                   "TECH_TO_OFFER": "Техническое → оффер"}
    for scope in sorted({r["scope"] for r in days_rows}):
        scope_rows = [r for r in days_rows if r["scope"] == scope]
        if not scope_rows:
            continue
        st.markdown(f"**{_direction_label(scope)}**")
        df = pd.DataFrame([{
            "Пара этапов": pair_labels.get(r["pair"], r["pair"]),
            "N": r["n"],
            "Среднее, дней": r["avg_days"],
            "Медиана, дней": r["median_days"],
            "Исключено (отриц.)": r["excluded_negative"],
        } for r in scope_rows])
        st.dataframe(df, hide_index=True, width="stretch")


# ---------------------------------------------------------------- Q12, Q13: срезы (US-15)

st.subheader("Срезы: канал общения, тип работодателя, формат")
st.caption("Q12, Q13. Процессы обоих инициаторов (D30). «Не указано» — отдельная строка.")

slices_rows = data.run_analysis_query("05-slices.sql", params)
if not slices_rows:
    st.info("Нет данных.")
else:
    dim_labels = {"COMM_CHANNEL": "Канал общения",
                  "APPLY_X_COMM": "Канал отклика × канал общения",
                  "EMPLOYER_TYPE": "Тип работодателя",
                  "EMPLOYMENT_FORMAT": "Формат трудоустройства"}
    slice_df = pd.DataFrame([{
        "Направление": _direction_label(r["direction"]),
        "Измерение": dim_labels.get(r["dimension"], r["dimension"]),
        "Значение 1": r["value_1"],
        "Значение 2": r["value_2"] or "",
        "Процессов": r["n_processes"],
        "N до тех.": r["n_tech"],
        "% до тех.": r["pct_tech"],
        "N до оффера": r["n_offer"],
        "% до оффера": r["pct_offer"],
    } for r in slices_rows])
    for dim in slice_df["Измерение"].unique():
        st.markdown(f"**{dim}**")
        st.dataframe(slice_df[slice_df["Измерение"] == dim].drop(columns="Измерение"),
                     hide_index=True, width="stretch")


# ---------------------------------------------------------------- Q8: причины отказов (US-16)

st.subheader("Причины отказов")
st.caption("Q8. Только процессы с текущим статусом «Отказ работодателя» или «Мой отказ» "
           "и указанной причиной (UQ4). «Нет ответа» в расчёт не входит.")

reason_rows = data.run_analysis_query("06-rejection-reasons.sql", params)
if not reason_rows:
    st.info("Нет данных.")
else:
    df = pd.DataFrame([{
        "Направление": _direction_label(r["direction"]),
        "Итог": r["outcome_name"],
        "Причина": r["reason_name"],
        "Процессов": r["n_processes"],
        "Доля, %": r["share_pct"],
    } for r in reason_rows])
    st.dataframe(df, hide_index=True, width="stretch")


# ---------------------------------------------------------------- Q5, Q6: навыки (US-17)

st.subheader("Рейтинг навыков и пробелы")
st.caption("Q5, Q6. Процессы, дошедшие до HR-интервью и далее, с введёнными навыками "
           "(D8, INV-17). Смещение выборки: это требования работодателей, пригласивших "
           "соискателя, а не рынок в целом (R8).")

skill_rows = data.run_analysis_query("07-skills.sql", params)
if not skill_rows:
    st.info("Нет данных.")
else:
    for direction in sorted({r["direction"] for r in skill_rows}):
        dir_rows = [r for r in skill_rows if r["direction"] == direction]
        if not dir_rows:
            continue
        sample_n = dir_rows[0]["n_sample"]
        st.markdown(f"**{_direction_label(direction)}** — процессов с навыками: {sample_n}"
                    + _small_n(sample_n))
        df = pd.DataFrame([{
            "Навык": r["skill"],
            "Процессов": r["n_processes"],
            "Доля, %": r["share_pct"],
            "В профиле": "да" if r["in_profile"] else "нет",
        } for r in dir_rows])
        st.dataframe(df, hide_index=True, width="stretch")


# ---------------------------------------------------------------- Q7: зарплатные вилки (US-18)

st.subheader("Зарплатные вилки «на руки»")
st.caption("Q7. Только процессы с известной вилкой (D15). Суммы введены «на руки» "
           "после самостоятельного пересчёта (R14). Выборка отражает только процессы, "
           "где вилка известна (R8).")

salary_rows = data.run_analysis_query("08-salaries.sql", params)
if not salary_rows:
    st.info("Нет данных.")
else:
    df = pd.DataFrame([{
        "Направление": _direction_label(r["scope"]),
        "N": r["n"],
        "Мин. середина, ₽": r["min_mid"],
        "Медиана середины, ₽": r["median_mid"],
        "Макс. середина, ₽": r["max_mid"],
    } for r in salary_rows])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("Середина вилки = среднее границ; если задана одна граница — используется она. "
               "Пометка «малая выборка» — если N меньше 10: "
               + ", ".join(f"{_direction_label(r['scope'])}: {r['n']}"
                            for r in salary_rows))