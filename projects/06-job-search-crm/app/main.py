"""Точка входа приложения Job Search CRM.

Запуск из корня проекта при активном виртуальном окружении:
    python -m streamlit run app/main.py
Для демонстрационной базы предварительно задайте в этом же терминале:
    $env:PGDATABASE = "job_search_crm_demo"
"""
import sys
from pathlib import Path

# Корень проекта нужен в путях поиска модулей, чтобы работали импорты `db` и `app`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import data  # noqa: E402

st.set_page_config(page_title="Job Search CRM", page_icon="📋", layout="wide")

try:
    info = data.database_info()
except Exception as error:  # база недоступна, не заполнен .env и т. п.
    st.error(f"Не удалось подключиться к базе данных: {error}")
    st.info("Проверьте файл .env (параметры PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) "
            "и что служба PostgreSQL запущена.")
    st.stop()

navigation = st.navigation([
    st.Page("views/reminders.py", title="Напоминания", icon="🔔", url_path="reminders", default=True),
    st.Page("views/processes.py", title="Процессы", icon="📋", url_path="processes"),
    st.Page("views/process_card.py", title="Карточка процесса", icon="🗂️", url_path="card"),
])

with st.sidebar:
    st.caption(f"База данных: {info['name']}")
if info["is_demo"]:
    st.warning("Демо-режим: показаны синтетические данные.", icon="🧪")

navigation.run()
