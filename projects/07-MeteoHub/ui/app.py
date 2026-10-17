"""
MeteoHub — Streamlit-дашборд.

Ходит в локальный FastAPI (http://127.0.0.1:8000).
Запуск: streamlit run ui/app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="MeteoHub", page_icon="🌤️", layout="wide")

st.title("🌤️ MeteoHub")
st.caption("REST API и дашборд — портфолио-кейс системного аналитика и техписателя")

# --- Боковая панель ---
with st.sidebar:
    st.header("Настройки")
    city = st.text_input("Населённый пункт", value="Новосибирск")
    forecast_days = st.slider("Дней прогноза", min_value=1, max_value=9, value=7)
    st.divider()
    st.info("Источники данных:\n- MET Norway (прогноз)\n- Open-Meteo (история)\n- Nominatim (геокодинг)")


def fetch(endpoint: str, params: dict) -> dict | None:
    """Хелпер: GET-запрос к API с обработкой ошибок."""
    try:
        response = requests.get(f"{API_BASE}{endpoint}", params=params, timeout=30)
        if response.status_code == 404:
            st.warning(f"Населённый пункт «{city}» не найден.")
            return None
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Ошибка API: {exc}")
        return None


# --- Загрузка данных ---
with st.spinner("Загрузка данных..."):
    current_data = fetch("/current", {"city": city})
    forecast_data = fetch("/forecast", {"city": city, "days": forecast_days})
    analytics_data = fetch("/analytics", {"city": city, "days": forecast_days})

if not current_data or not forecast_data:
    st.stop()

# --- Вкладки ---
tab_current, tab_forecast, tab_analytics = st.tabs(
    ["🌡️ Текущая погода", "📈 Прогноз и графики", "📊 Аналитика"]
)

# ==========================================
# ВКЛАДКА 1: Текущая погода
# ==========================================
with tab_current:
    st.header(f"Погода сейчас: {current_data['city']}")
    st.caption(f"Часовой пояс: {current_data.get('timezone', 'UTC')}")
    
    # Метрики
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Температура", f"{current_data.get('temperature_c', '—')} °C")
    col2.metric("Ветер", f"{current_data.get('wind_speed_ms', '—')} м/с")
    col3.metric("Влажность", f"{current_data.get('humidity_pct', '—')} %")
    col4.metric("Давление", f"{current_data.get('pressure_mmhg', '—')} мм рт. ст.")

    st.subheader("Детали")
    col5, col6, col7 = st.columns(3)
    col5.write(f"**Состояние:** {current_data.get('weather_description', '—')}")
    col6.write(f"**Осадки (след. час):** {current_data.get('precipitation_next_1h_mm', 0)} мм")
    col7.write(f"**Облачность:** {current_data.get('cloud_cover_pct', '—')} %")
    
    st.caption(f"Время наблюдения (UTC): {current_data.get('time', '—')}")


# ==========================================
# ВКЛАДКА 2: Прогноз и графики
# ==========================================
with tab_forecast:
    st.header(f"Прогноз для {forecast_data['city']}")
    
    hourly = forecast_data.get("hourly", [])
    daily = forecast_data.get("daily", [])

    if hourly:
        df_hourly = pd.DataFrame(hourly)
        tz_str = forecast_data.get("timezone", "UTC")
        # Парсим ISO-время (оно в UTC) и переводим в локальный пояс города
        df_hourly["time"] = pd.to_datetime(df_hourly["time"]).dt.tz_convert(tz_str)

        # 1. Линейный график температуры по часам
        st.subheader("Температура по часам")
        fig_temp = px.line(
            df_hourly, x="time", y="temperature_c",
            labels={"time": f"Время ({tz_str})", "temperature_c": "Температура (°C)"},
            markers=True,
        )
        fig_temp.update_layout(hovermode="x unified")
        st.plotly_chart(fig_temp, width='stretch')

        # 2. Столбчатая диаграмма осадков
        st.subheader("Осадки по часам")
        fig_precip = px.bar(
            df_hourly, x="time", y="precipitation_mm",
            labels={"time": f"Время ({tz_str})", "precipitation_mm": "Осадки (мм)"},
            color_discrete_sequence=["#3b82f6"],
        )
        fig_precip.update_layout(hovermode="x unified")
        st.plotly_chart(fig_precip, width='stretch')

        # 3. Роза ветров
        st.subheader("Роза ветров")
        # Для розы ветров нужна агрегация: считаем среднюю скорость по направлениям
        df_wind = df_hourly.dropna(subset=["wind_direction_deg", "wind_speed_ms"])
        if not df_wind.empty:
            # Округляем направление до 16 румбов (через 22.5 градуса)
            import numpy as np
            df_wind["direction_bin"] = (df_wind["wind_direction_deg"] / 22.5).round() * 22.5
            # Группируем: средняя скорость и количество часов
            df_wind_grouped = df_wind.groupby("direction_bin").agg(
                mean_speed=("wind_speed_ms", "mean"),
                count=("wind_speed_ms", "count")
            ).reset_index()

            fig_wind = px.bar_polar(
                df_wind_grouped, r="mean_speed", theta="direction_bin",
                color="mean_speed", template="plotly_dark",
                labels={"direction_bin": "Направление (°)", "mean_speed": "Скорость (м/с)"},
                color_continuous_scale="Blues",
            )
            fig_wind.update_layout(
                polar=dict(angularaxis=dict(direction="clockwise", rotation=90)),
                showlegend=False,
            )
            st.plotly_chart(fig_wind, width='stretch')
        else:
            st.info("Нет данных о ветре для построения розы.")

    # Сводная таблица по дням
    st.subheader("Сводка по дням")
    if daily:
        df_daily = pd.DataFrame(daily)
        df_daily = df_daily[[
            "date", "temperature_max_c", "temperature_min_c", 
            "precipitation_sum_mm", "wind_speed_max_ms", "weather_description"
        ]]
        df_daily.columns = [
            "Дата", "Макс. темп (°C)", "Мин. темп (°C)", 
            "Осадки (мм)", "Макс. ветер (м/с)", "Погода"
        ]
        st.dataframe(df_daily, width='stretch', hide_index=True)


# ==========================================
# ВКЛАДКА 3: Аналитика
# ==========================================
with tab_analytics:
    st.header(f"Сводка за {forecast_days} дней: {analytics_data['city']}")
    
    if not analytics_data:
        st.warning("Аналитические данные недоступны.")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            warmest = analytics_data.get("warmest")
            if warmest:
                st.success(f"**Самый тёплый день:** {warmest['date']} — {warmest['value']} °C ({warmest.get('weather_description', '')})")
            
            wettest = analytics_data.get("wettest")
            if wettest:
                st.info(f"**Самый дождливый день:** {wettest['date']} — {wettest['value']} мм ({wettest.get('weather_description', '')})")

        with col2:
            coldest = analytics_data.get("coldest")
            if coldest:
                st.warning(f"**Самый холодный день:** {coldest['date']} — {coldest['value']} °C ({coldest.get('weather_description', '')})")
            
            windiest = analytics_data.get("windiest")
            if windiest:
                st.error(f"**Самый ветреный день:** {windiest['date']} — {windiest['value']} м/с ({windiest.get('weather_description', '')})")