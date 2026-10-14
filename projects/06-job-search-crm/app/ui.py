"""Общие элементы интерфейса Streamlit."""
import streamlit as st

CARD_PAGE = "views/process_card.py"


def open_card(process_id: int) -> None:
    """Запоминает выбранный процесс и переходит на страницу карточки."""
    st.session_state["process_id"] = process_id
    st.switch_page(CARD_PAGE)


def open_card_button(process_id: int | None, label: str = "Открыть карточку выбранного процесса") -> None:
    """Кнопка перехода к карточке; показывается, только если строка в таблице выбрана."""
    if process_id is not None and st.button(label, type="primary"):
        open_card(process_id)
