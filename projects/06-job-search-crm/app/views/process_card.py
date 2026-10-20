"""Страница «Карточка процесса»: поля, действия, история этапов, навыки.

Действия:
  * «Назначить этап» (US-04) — с подтверждением нетипичных переходов.
  * «Закрыть процесс» (US-06) — с выбором итога и причины отказа (SR9).
  * «Изменить поля» (US-05) — правка атрибутов карточки; удаление процесса.
  * Редактирование и удаление записи истории (US-05, D33).

Тестовое задание — обычный этап (D32, ADR-002): отдельного блока нет, срок и результат
пишутся текстом в комментарии к записи этапа «Тестовое задание».
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

# Справочники — для формы правки (US-05).
directions_ref = data.get_reference("directions")
vacancy_sources_ref = data.get_reference("vacancy_sources")
apply_channels_ref = data.get_apply_channels()
all_channels_ref = data.get_reference("channels")
employer_types_ref = data.get_reference("employer_types")
employment_formats_ref = data.get_reference("employment_formats")


def _index_of(rows: list[dict], code: str | None, default: int = 0) -> int:
    """Индекс строки с заданным code; default, если code не найден или None."""
    if code is None:
        return default
    for i, row in enumerate(rows):
        if row["code"] == code:
            return i
    return default


def _duration_days(process: dict, history: list[dict]) -> int:
    """Длительность процесса в календарных днях (как в списке процессов).

    Дата начала — минимальная stage_date среди записей-этапов (DQ7). Конец: для закрытых
    процессов — stage_date последней записи истории (записи упорядочены по recorded_at desc,
    id desc, поэтому history[0] — последняя); для открытых — сегодня. Результат не меньше 0:
    для процессов с датами только в будущем — 0.
    """
    stage_dates = [h["stage_date"] for h in history if h["status_kind"] == "stage"]
    if not stage_dates:
        return 0
    start = min(stage_dates)
    if process["status_kind"] == "outcome" and history:
        end = history[0]["stage_date"]
    else:
        end = date.today()
    return max(0, (end - start).days)


duration_days = _duration_days(process, card["history"])

st.title(f"{process['company_name']}: {process['vacancy_title']}")
st.markdown(f"**Статус:** {process['status']} · **Направление:** {process['direction']} · "
            f"**Инициатор:** {fmt.initiator_label(process['initiator'])} · "
            f"**Длительность:** {duration_days} дн.")

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

PENDING_STAGE = "pending_stage_change"
PENDING_CLOSE = "pending_close_change"
PENDING_WARNS = "pending_warnings"


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


tab_stage, tab_close, tab_edit = st.tabs(["Назначить этап", "Закрыть процесс", "Изменить поля"])

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
        st.caption("Причина обязательна, если в истории есть HR-интервью, тестовое или позже (SR9).")

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


# ---------------------------------------------------------------- изменение полей (US-05)

# Ключи формы привязаны к id процесса: при переходе на другую карточку значения сбрасываются.
# После сохранения очищаем ключи — форма перечитывает значения из базы.
def _edit_key(name: str) -> str:
    return f"edit_{name}_{process_id}"


def _clear_edit_keys() -> None:
    prefix = "edit_"
    suffix = f"_{process_id}"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix) and key.endswith(suffix):
            st.session_state.pop(key, None)


with tab_edit:
    edit = data.get_process_field_codes(process_id)
    st.caption("Правка полей карточки (US-05). Инициатор после создания не меняется (INV-19); "
               "при ошибке в инициаторе процесс удаляют и создают заново.")

    edit_dir_name = st.selectbox(
        "Направление", options=[d["name_ru"] for d in directions_ref],
        index=_index_of(directions_ref, edit["direction_code"]),
        key=_edit_key("direction"))
    edit_dir_code = next(d["code"] for d in directions_ref if d["name_ru"] == edit_dir_name)

    edit_company = st.text_input("Компания", value=edit["company_name"], key=_edit_key("company"))
    edit_title = st.text_input("Название вакансии", value=edit["vacancy_title"], key=_edit_key("title"))
    edit_url = st.text_input("Ссылка на вакансию", value=edit["vacancy_url"] or "", key=_edit_key("url"))

    edit_source_code = None
    edit_apply_code = None
    if edit["initiator"] == "applicant":
        edit_source_name = st.selectbox(
            "Источник вакансии", options=[s["name_ru"] for s in vacancy_sources_ref],
            index=_index_of(vacancy_sources_ref, edit["vacancy_source_code"]),
            key=_edit_key("source"))
        edit_source_code = next(s["code"] for s in vacancy_sources_ref if s["name_ru"] == edit_source_name)

        edit_apply_name = st.selectbox(
            "Канал отклика", options=[c["name_ru"] for c in apply_channels_ref],
            index=_index_of(apply_channels_ref, edit["apply_channel_code"]),
            key=_edit_key("apply"))
        edit_apply_code = next(c["code"] for c in apply_channels_ref if c["name_ru"] == edit_apply_name)
    else:
        st.caption("Для входящего процесса источник вакансии и канал отклика не заполняются (D11).")

    edit_comm_name = st.selectbox(
        "Канал общения", options=[c["name_ru"] for c in all_channels_ref],
        index=_index_of(all_channels_ref, edit["communication_channel_code"]),
        key=_edit_key("comm"))
    edit_comm_code = next(c["code"] for c in all_channels_ref if c["name_ru"] == edit_comm_name)

    col_et, col_ef = st.columns(2)
    with col_et:
        et_options = ["—"] + [e["name_ru"] for e in employer_types_ref]
        et_index = (_index_of(employer_types_ref, edit["employer_type_code"]) + 1
                    if edit["employer_type_code"] else 0)
        et_name = st.selectbox("Тип работодателя", options=et_options, index=et_index,
                               key=_edit_key("et"))
        edit_et_code = None if et_name == "—" else next(
            e["code"] for e in employer_types_ref if e["name_ru"] == et_name)
    with col_ef:
        ef_options = ["—"] + [e["name_ru"] for e in employment_formats_ref]
        ef_index = (_index_of(employment_formats_ref, edit["employment_format_code"]) + 1
                    if edit["employment_format_code"] else 0)
        ef_name = st.selectbox("Формат трудоустройства", options=ef_options, index=ef_index,
                               key=_edit_key("ef"))
        edit_ef_code = None if ef_name == "—" else next(
            e["code"] for e in employment_formats_ref if e["name_ru"] == ef_name)

    col_sf, col_st = st.columns(2)
    with col_sf:
        edit_sf = st.number_input("Вилка «от», ₽", min_value=0, step=1000,
                                  value=int(edit["salary_from"] or 0),
                                  key=_edit_key("sf"))
    with col_st:
        edit_st = st.number_input("Вилка «до», ₽", min_value=0, step=1000,
                                  value=int(edit["salary_to"] or 0),
                                  key=_edit_key("st"))

    edit_cn = st.text_input("Контакт: имя", value=edit["contact_name"] or "", key=_edit_key("cn"))
    edit_cp = st.text_input("Контакт: должность", value=edit["contact_position"] or "",
                            key=_edit_key("cp"))
    edit_note = st.text_area("Комментарий", value=edit["note"] or "", key=_edit_key("note"))

    if st.button("Сохранить изменения", type="primary", key=_edit_key("save_btn")):
        try:
            data.update_process_fields(
                process_id,
                direction_code=edit_dir_code,
                company_name=edit_company,
                vacancy_title=edit_title,
                communication_channel_code=edit_comm_code,
                vacancy_url=edit_url.strip() or None,
                vacancy_source_code=edit_source_code,
                apply_channel_code=edit_apply_code,
                employer_type_code=edit_et_code,
                employment_format_code=edit_ef_code,
                salary_from=int(edit_sf) if edit_sf > 0 else None,
                salary_to=int(edit_st) if edit_st > 0 else None,
                contact_name=edit_cn.strip() or None,
                contact_position=edit_cp.strip() or None,
                note=edit_note.strip() or None,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _clear_edit_keys()
            st.success("Поля процесса обновлены.")
            st.rerun()

    st.divider()
    st.subheader("Удалить процесс")
    st.caption("Действие необратимо: процесс, его история этапов и связи с навыками "
               "удаляются безвозвратно (US-05, критерий 5).")
    confirm_delete = st.checkbox("Подтверждаю удаление", key=_edit_key("delete_confirm"))
    if st.button("Удалить процесс", disabled=not confirm_delete,
                 key=_edit_key("delete_btn")):
        try:
            data.delete_process(process_id)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.pop("process_id", None)
            st.switch_page("views/processes.py")


# ---------------------------------------------------------------- история этапов (US-05, D33)

st.subheader("История этапов")
st.caption("Сверху — самые свежие записи (по дате записи, затем по id). "
           "Зелёный фон — этапы, красный — итоги.")

history_kinds = [row["status_kind"] for row in card["history"]]

history_df = pd.DataFrame([
    {"Дата записи": row["recorded_at"],
     "Дата этапа": pd.Timestamp(row["stage_date"]),
     "Статус": row["status"],
     "Причина отказа": row["reason"] or "",
     "Комментарий": row["note"] or ""}
    for row in card["history"]
])
# recorded_at хранится с временем — обрезаем до дня, сохраняя тип datetime64
history_df["Дата записи"] = pd.to_datetime(history_df["Дата записи"]).dt.normalize()


def _highlight_history_row(row):
    color = ("rgba(76, 175, 80, 0.22)" if history_kinds[row.name] == "stage"
             else "rgba(244, 67, 54, 0.22)")
    return [f"background-color: {color}"] * len(row)


st.dataframe(history_df.style.apply(_highlight_history_row, axis=1),
             hide_index=True, width="stretch",
             column_config={
                 "Дата записи": st.column_config.DateColumn(format="DD.MM.YYYY"),
                 "Дата этапа": st.column_config.DateColumn(format="DD.MM.YYYY"),
             })

# Выбор записи для правки/удаления. Клик по строке с цветной таблицей несовместим
# (Streamlit: Styler + on_select), поэтому выбираем через selectbox.
st.markdown("**Редактировать или удалить запись**")
st.caption("Выберите запись, измените поля и сохраните — или удалите запись с подтверждением.")

if not card["history"]:
    st.info("Записей истории нет.")
else:
    # Понятные подписи: дата записи, статус, дата этапа
    record_options: dict[str, dict] = {}
    for row in card["history"]:
        label = (f"{fmt.format_date(row['recorded_at'])} — {row['status']} "
                 f"(этап {fmt.format_date(row['stage_date'])})")
        record_options[label] = row

    chosen_label = st.selectbox("Запись истории", options=list(record_options),
                                key=f"history_choice_{process_id}")
    chosen = record_options[chosen_label]

    # Форма редактирования (раскрыта по умолчанию — самое частое действие)
    with st.expander("Редактировать запись", expanded=False):
        # Статус: этапы + итоги. Показываем отдельно группы, чтобы не путать.
        status_options: list[tuple[str, str]] = (
            [(s["code"], s["name_ru"] + " (этап)") for s in stages]
            + [(o["code"], o["name_ru"] + " (итог)") for o in outcomes]
        )
        status_codes = [code for code, _ in status_options]
        status_labels = [label for _, label in status_options]
        current_index = status_codes.index(chosen["status_code"]) if chosen["status_code"] in status_codes else 0

        new_status_label = st.selectbox(
            "Статус", options=status_labels, index=current_index,
            key=f"history_status_{chosen['id']}")
        new_status_code = status_codes[status_labels.index(new_status_label)]

        new_stage_date = st.date_input(
            "Дата этапа", value=chosen["stage_date"], format="DD.MM.YYYY",
            key=f"history_date_{chosen['id']}")
        new_note = st.text_input(
            "Комментарий", value=chosen["note"] or "",
            key=f"history_note_{chosen['id']}",
            help="Для этапа «Тестовое задание» сюда можно записать срок сдачи и результат.")

        # Причина отказа — только если новый статус — один из отказов (INV-08)
        new_reason_code: str | None = None
        if new_status_code in ("REJECTED_BY_EMPLOYER", "WITHDRAWN_BY_ME"):
            reason_options = ["—"] + [r["name_ru"] for r in rejection_reasons]
            current_reason_name = next(
                (r["name_ru"] for r in rejection_reasons if r["code"] == chosen["reason_code"]), "—")
            current_reason_index = reason_options.index(current_reason_name) if current_reason_name in reason_options else 0
            new_reason_name = st.selectbox(
                "Причина отказа", options=reason_options, index=current_reason_index,
                key=f"history_reason_{chosen['id']}")
            if new_reason_name != "—":
                new_reason_code = next(r["code"] for r in rejection_reasons if r["name_ru"] == new_reason_name)
            st.caption("Причина обязательна для отказа, если в истории есть HR-интервью, "
                       "тестовое или позже (SR9).")

        st.caption("Если изменяется статус не у последней записи, текущий статус процесса "
                   "не изменится (порядок записей: дата записи, затем id).")

        if st.button("Сохранить запись", type="primary",
                     key=f"history_save_{chosen['id']}"):
            try:
                data.update_history_record(
                    chosen["id"],
                    status_code=new_status_code,
                    stage_date=new_stage_date,
                    note=new_note.strip() or None,
                    rejection_reason_code=new_reason_code,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Запись обновлена.")
                st.rerun()

    # Удаление записи
    with st.expander("Удалить запись", expanded=False):
        st.caption("Удаление необратимо. Единственную запись истории удалить нельзя (INV-18).")
        confirm = st.checkbox("Подтверждаю удаление записи",
                              key=f"history_del_confirm_{chosen['id']}")
        if st.button("Удалить запись", disabled=not confirm,
                     key=f"history_del_{chosen['id']}"):
            try:
                data.delete_history_record(chosen["id"])
            except Exception as error:                          # noqa: BLE001
                st.error(str(error))
            else:
                st.success("Запись удалена.")
                st.rerun()


# ---------------------------------------------------------------- навыки вакансии (US-11)

st.subheader("Навыки вакансии")
st.caption("Навыки вакансии (US-11). Вводятся с этапа HR-интервью и далее (D8), "
           "но хранятся независимо от текущего статуса. Подсказки — по направлению процесса.")

current_skills = card["skills"]
suggestions = data.get_direction_skill_suggestions(process["direction_code"])
all_skills_from_ref = data.get_all_skills()
all_skill_options = sorted(
    {*suggestions, *current_skills, *all_skills_from_ref}, key=str.lower
)

selected_skills = st.multiselect(
    "Навыки",
    options=all_skill_options,
    default=current_skills,
    accept_new_options=True,
    key=f"skills_select_{process_id}",
    help="Выберите из списка или введите новые. Для нескольких новых — через запятую.",
)

if st.button("Сохранить навыки", type="primary", key=f"skills_save_{process_id}"):
    try:
        data.set_process_skills(process_id, selected_skills)
    except ValueError as error:
        st.error(str(error))
    else:
        st.success("Навыки сохранены.")
        st.rerun()