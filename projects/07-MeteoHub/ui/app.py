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
import json
import os

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="MeteoHub", page_icon="🌤️", layout="wide")

# Цветовая шкала по мотивам Яндекс.Погоды
yandex_scale = [
    (0.0, "#340c4a"),    # -40 °C: темно-фиолетовый
    (0.125, "#191c9a"),  # -30 °C: темно-синий
    (0.25, "#2d6fe6"),   # -20 °C: синий
    (0.375, "#5ac2d6"),  # -10 °C: голубой
    (0.5, "#35a36e"),    # 0 °C: зеленый
    (0.625, "#a8c746"),  # +10 °C: желто-зеленый
    (0.75, "#f5a623"),   # +20 °C: оранжевый
    (0.875, "#e24b33"),  # +30 °C: красно-оранжевый
    (1.0, "#851d29")     # +40 °C: темно-красный
]

# --- Логика Избранного ---
FAV_FILE = "ui/favorites.json"

def load_favorites() -> list[dict]:
    if os.path.exists(FAV_FILE):
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_favorites(favs: list[dict]) -> None:
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(favs, f, ensure_ascii=False, indent=2)

# Инициализация состояния
if "favorites" not in st.session_state:
    st.session_state["favorites"] = load_favorites()

# Скрываем назойливую подсказку "Press Enter..." в полях ввода
st.markdown(
    """
    <style>
    div[data-testid="InputInstructions"] {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🌤️ MeteoHub")
st.caption("REST API и дашборд — портфолио-кейс системного аналитика и техписателя")

# --- Боковая панель ---
with st.sidebar:
    st.header("Настройки")
    
    if "selected_city" not in st.session_state:
        st.session_state["selected_city"] = "Новосибирск"
        st.session_state["search_results"] = []

    with st.form(key="search_form"):
        search_query = st.text_input("Поиск населённого пункта", placeholder="Например, Москва")
        submit_button = st.form_submit_button("🔍 Найти")
    
    if submit_button and search_query:
        with st.spinner("Поиск..."):
            try:
                resp = requests.get(f"{API_BASE}/geocode/search", params={"name": search_query}, timeout=15)
                if resp.status_code == 200:
                    results = resp.json()
                    st.session_state["search_results"] = results
                    if not results:
                        st.warning("Ничего не найдено. Попробуйте изменить запрос.")
                    else:
                        st.session_state["selected_city"] = results[0]["city"]
                else:
                    st.error("Ошибка сервера при поиске.")
            except Exception as e:
                st.error(f"Ошибка API: {e}")

    if st.session_state["search_results"]:
        options = [r["city"] for r in st.session_state["search_results"]]
        
        if st.session_state["selected_city"] not in options:
            st.session_state["selected_city"] = options[0]
            
        st.selectbox("Найденные варианты:", options=options, key="selected_city")
        
    city = st.session_state["selected_city"]
    
    # --- Блок добавления в избранное ---
    col_city, col_btn = st.columns([3, 1])
    with col_city:
        st.info(f"**{city}**")
    with col_btn:
        # Проверяем, нет ли уже этого города в избранном
        is_fav = any(f["full_name"] == city for f in st.session_state["favorites"])
        if not is_fav:
            if st.button("⭐", help="Добавить в избранное", use_container_width=True):
                if len(st.session_state["favorites"]) >= 5:
                    st.error("Максимум 5 городов!")
                else:
                    short_name = city.split(",")[0].strip()
                    st.session_state["favorites"].append({"short_name": short_name, "full_name": city})
                    save_favorites(st.session_state["favorites"])
                    st.rerun()
        else:
            st.button("✅", disabled=True, help="Уже в избранном", use_container_width=True)

    forecast_days = st.slider("Дней прогноза", min_value=1, max_value=9, value=2)
    st.divider()
    
    # --- Блок Избранного ---
    st.subheader("⭐ Избранное")
    if not st.session_state["favorites"]:
        st.caption("Пока пусто. Добавьте город с помощью кнопки ⭐ выше.")
    
    # Функция-коллбэк для переключения города
    def switch_city(full_name: str):
        st.session_state["selected_city"] = full_name
        st.session_state["search_results"] = [] # Сбрасываем поиск, чтобы selectbox не мешал

    for i, fav in enumerate(st.session_state["favorites"]):
        col_city, col_edit, col_del = st.columns([4, 1.5, 1.5])
        
        with col_city:
            # Передаем функцию switch_city в on_click. 
            # Streamlit сам вызовет st.rerun() после её выполнения.
            st.button(
                fav["short_name"], 
                key=f"go_{i}", 
                help="Перейти к этому городу", 
                type="tertiary", 
                use_container_width=True,
                on_click=switch_city,
                args=(fav["full_name"],)
            )
                
        with col_edit:
            if st.button("✏️", key=f"edit_{i}", help="Переименовать", use_container_width=True):
                st.session_state[f"editing_{i}"] = True
                
        with col_del:
            if st.button("🗑️", key=f"del_{i}", help="Удалить", use_container_width=True):
                st.session_state["favorites"].pop(i)
                save_favorites(st.session_state["favorites"])
                st.rerun()
        
        # Поле для переименования
        if st.session_state.get(f"editing_{i}"):
            with st.container():
                new_name = st.text_input("Новое название", value=fav["short_name"], key=f"input_{i}")
                if st.button("Сохранить", key=f"save_{i}"):
                    st.session_state["favorites"][i]["short_name"] = new_name
                    save_favorites(st.session_state["favorites"])
                    st.session_state[f"editing_{i}"] = False
                    st.rerun()
                
    st.divider()
    st.caption("Источники: MET Norway, Open-Meteo, Nominatim")

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

        # Фильтруем почасовые данные по ползунку из сайдбара
        end_time = df_hourly["time"].min() + pd.Timedelta(days=forecast_days)
        df_hourly = df_hourly[df_hourly["time"] < end_time].copy()

        if not df_hourly.empty:

            # Определяем общие границы по времени для обоих графиков
            x_min = df_hourly["time"].min()
            x_max = df_hourly["time"].max()

            # 1. Создаем график температуры
            fig_temp = px.scatter(
                df_hourly, 
                x="time", 
                y="temperature_c",
                color="temperature_c",
                color_continuous_scale=yandex_scale,
                range_color=[-40, 40],
                labels={"time": f"Время ({tz_str})", "temperature_c": "Температура (°C)"},
            )
            fig_temp.update_traces(
                mode="lines+markers",
                line=dict(color="rgba(150, 150, 150, 0.5)", width=2),
                marker=dict(size=8, line=dict(width=1, color='DarkSlateGrey'))
            )
            fig_temp.update_layout(
                hovermode="x unified",
                coloraxis_colorbar=dict(title="Температура (°C)"),
                margin=dict(l=60, r=60, t=30, b=30), # Одинаковые жесткие отступы
                xaxis=dict(range=[x_min, x_max], automargin=False)
            )
            fig_temp.update_yaxes(automargin=False)

            # 2. Создаем график осадков
            fig_precip = px.bar(
                df_hourly, x="time", y="precipitation_mm",
                labels={"time": f"Время ({tz_str})", "precipitation_mm": "Осадки (мм)"},
                color_discrete_sequence=["#3b82f6"],
            )
            fig_precip.update_layout(
                hovermode="x unified",
                margin=dict(l=60, r=60, t=30, b=30), # Точно такие же отступы
                xaxis=dict(range=[x_min, x_max], automargin=False),
                bargap=0.1
            )
            fig_precip.update_yaxes(automargin=False)

            # 3. Создаем общий график с двумя подграфиками (общая ось X)
            from plotly.subplots import make_subplots
            import plotly.graph_objects as go

            fig_combined = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.1,
                subplot_titles=("Температура по часам", "Осадки по часам")
            )

            # Добавляем график температуры
            fig_combined.add_trace(
                go.Scatter(
                    x=df_hourly["time"], 
                    y=df_hourly["temperature_c"],
                    mode="lines+markers",
                    marker=dict(
                        color=df_hourly["temperature_c"], 
                        colorscale=yandex_scale, 
                        cmin=-40, cmax=40, 
                        size=8, 
                        line=dict(width=1, color='DarkSlateGrey'),
                        colorbar=dict(title="Температура (°C)", len=0.45, y=0.78) # Шкала для верхнего графика
                    ),
                    line=dict(color="rgba(150, 150, 150, 0.5)", width=2),
                    name="Температура"
                ),
                row=1, col=1
            )

            # Добавляем график осадков
            fig_combined.add_trace(
                go.Bar(
                    x=df_hourly["time"], 
                    y=df_hourly["precipitation_mm"],
                    marker_color="#3b82f6",
                    name="Осадки"
                ),
                row=2, col=1
            )

            # 4. Фон и разделители (применяются к обоим графикам сразу через row="all")
            unique_dates = df_hourly["time"].dt.date.unique()
            
            for i, date_obj in enumerate(unique_dates):
                day_start = pd.Timestamp(date_obj).tz_localize(df_hourly["time"].dt.tz)
                day_end = day_start + pd.Timedelta(days=1)

                rect_x0 = max(day_start, x_min)
                rect_x1 = min(day_end, x_max)

                if i % 2 == 0:
                    fig_combined.add_vrect(
                        x0=rect_x0, x1=rect_x1,
                        fillcolor="rgba(128, 128, 128, 0.15)",
                        layer="below", line_width=0,
                        row="all", col=1 # Применяем к обоим графикам
                    )
                
                if i > 0:
                    fig_combined.add_vline(
                        x=day_start, line_width=1, line_dash="dot", line_color="rgba(128, 128, 128, 0.5)",
                        row="all", col=1 # Применяем к обоим графикам
                    )

            # Настраиваем общий вид
            fig_combined.update_layout(
                height=600, 
                hovermode="x unified",
                margin=dict(l=60, r=60, t=50, b=30),
                showlegend=False
            )
            
            # Включаем сетку для обоих графиков
            fig_combined.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128, 128, 128, 0.2)')
            fig_combined.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128, 128, 128, 0.2)')
            
            # Отображаем единый график
            st.plotly_chart(fig_combined, width='stretch')

        # 3. Роза ветров
        st.subheader("Роза ветров")
        # Для розы ветров нужна агрегация: считаем среднюю скорость по направлениям
        df_wind = df_hourly.dropna(subset=["wind_direction_deg", "wind_speed_ms"])
        if not df_wind.empty:
            import numpy as np
            # Округляем направление до 8 основных румбов (через 45 градусов)
            df_wind["direction_bin"] = (df_wind["wind_direction_deg"] / 45).round() * 45
            
            # Группируем: считаем МАКСИМАЛЬНУЮ скорость в каждом направлении
            df_wind_grouped = df_wind.groupby("direction_bin").agg(
                max_speed=("wind_speed_ms", "max")
            ).reset_index()

            # Маппинг градусов в текстовые направления (только 8 основных)
            compass = {
                0: "С", 45: "СВ", 90: "В", 135: "ЮВ", 
                180: "Ю", 225: "ЮЗ", 270: "З", 315: "СЗ"
            }
            compass_vals = list(compass.keys())
            compass_texts = list(compass.values())

            fig_wind = px.bar_polar(
                df_wind_grouped, r="max_speed", theta="direction_bin",
                color="max_speed", template="plotly_dark",
                labels={"direction_bin": "Направление", "max_speed": "Скорость (м/с)"},
                color_continuous_scale="Blues",
            )
            fig_wind.update_layout(
                polar=dict(
                    radialaxis=dict(
                        range=[0, 9],
                        dtick=3,
                        angle=90,
                        tickangle=90
                    ),
                    angularaxis=dict(
                        direction="clockwise", 
                        rotation=90,
                        tickmode="array",
                        tickvals=compass_vals,
                        ticktext=compass_texts
                    )
                ),
                showlegend=False,
            )
            st.plotly_chart(fig_wind, width='stretch')
        else:
            st.info("Нет данных о ветре для построения розы.")

    # --- ДНЕВНЫЕ ГРАФИКИ ---
    st.divider()
    st.subheader("Дневной прогноз")
    
    if daily:
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go
        
        df_daily_plot = pd.DataFrame(daily)
        # Обрезаем по ползунку из сайдбара
        df_daily_plot = df_daily_plot.head(forecast_days)

        # Создаем общий график с двумя подграфиками (общая ось X)
        fig_daily_combined = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.12,
            subplot_titles=("Температура (max / mean / min)", "Осадки за день")
        )

        # 1. График температуры (Вариант А: закрашенная область + линия)
        # Закрашенная область от min до max
        fig_daily_combined.add_trace(
            go.Scatter(
                x=df_daily_plot["date"], y=df_daily_plot["temperature_max_c"],
                mode='lines', name='Максимум',
                line=dict(width=0), showlegend=False,
                hovertemplate='Максимальная: %{y:.1f} °C<extra></extra>'
            ),
            row=1, col=1
        )
        fig_daily_combined.add_trace(
            go.Scatter(
                x=df_daily_plot["date"], y=df_daily_plot["temperature_min_c"],
                mode='lines', name='Минимум',
                line=dict(width=0), 
                fill='tonexty', 
                # Применяем вертикальный градиент
                fillgradient=dict(
                    type="vertical",
                    colorscale=yandex_scale,
                    start=-40,
                    stop=40
                ),
                showlegend=False,
                hovertemplate='Минимальная: %{y:.1f} °C<extra></extra>'
            ),
            row=1, col=1
        )
        
        # Создаем общий график с двумя подграфиками (общая ось X)
        fig_daily_combined = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.12,
            subplot_titles=("Температура (max / mean / min)", "Осадки за день")
        )

        # 1. Линия "Максимум" (добавляется первой, чтобы заливка легла поверх неё)
        fig_daily_combined.add_trace(
            go.Scatter(
                x=df_daily_plot["date"], y=df_daily_plot["temperature_max_c"],
                mode='lines', name='Максимум',
                line=dict(width=0), showlegend=False,
                hoverinfo='skip'  # <--- СКРЫВАЕМ ПОДСКАЗКУ
            ),
            row=1, col=1
        )

        # 2. Линия "Минимум" + градиентная заливка между min и max
        fig_daily_combined.add_trace(
            go.Scatter(
                x=df_daily_plot["date"], y=df_daily_plot["temperature_min_c"],
                mode='lines', name='Минимум',
                line=dict(width=0), 
                fill='tonexty', 
                fillgradient=dict(
                    type="vertical",
                    colorscale=yandex_scale,
                    start=-40,
                    stop=40
                ),
                showlegend=False,
                hoverinfo='skip'  # <--- СКРЫВАЕМ ПОДСКАЗКУ
            ),
            row=1, col=1
        )

        # 3. Линия "Средняя" (собирает данные о min и max для подсказки)
        fig_daily_combined.add_trace(
            go.Scatter(
                x=df_daily_plot["date"], y=df_daily_plot["temperature_mean_c"],
                mode='lines+markers', name='Средняя',
                
                # Передаем макс и мин во встроенные данные
                customdata=df_daily_plot[['temperature_max_c', 'temperature_min_c']].values,
                
                # Формируем кастомную подсказку с нужным порядком
                hovertemplate=(
                    'Максимальная: %{customdata[0]:.1f} °C<br>'
                    'Средняя: %{y:.1f} °C<br>'
                    'Минимальная: %{customdata[1]:.1f} °C'
                    '<extra></extra>'
                ),
                legendrank=2,
                line=dict(color="black", width=3),
                marker=dict(
                    color=df_daily_plot["temperature_mean_c"],
                    colorscale=yandex_scale,
                    cmin=-40, cmax=40,
                    size=10,
                    line=dict(width=1, color='DarkSlateGrey'),
                    colorbar=dict(title="Температура (°C)", len=0.45, y=0.78)
                )
            ),
            row=1, col=1
        )

        # 4. График дневных осадков
        fig_daily_combined.add_trace(
            go.Bar(
                x=df_daily_plot["date"], y=df_daily_plot["precipitation_sum_mm"],
                marker_color="#3b82f6",
                name="Осадки",
                legendrank=4
            ),
            row=2, col=1
        )

        # Настраиваем общий вид
        fig_daily_combined.update_layout(
            height=600,
            hovermode="x unified",
            margin=dict(l=60, r=60, t=50, b=30),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # Включаем сетку для обоих графиков
        fig_daily_combined.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128, 128, 128, 0.2)')
        fig_daily_combined.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128, 128, 128, 0.2)')

        st.plotly_chart(fig_daily_combined, width='stretch')

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
                # Красный для самого теплого
                st.error(f"**Самый тёплый день:** {warmest['date']} — {warmest['value']} °C ({warmest.get('weather_description', '')})")
            
            wettest = analytics_data.get("wettest")
            if wettest:
                # Зеленый для самого дождливого
                st.success(f"**Самый дождливый день:** {wettest['date']} — {wettest['value']} мм ({wettest.get('weather_description', '')})")

        with col2:
            coldest = analytics_data.get("coldest")
            if coldest:
                # Синий для самого холодного
                st.info(f"**Самый холодный день:** {coldest['date']} — {coldest['value']} °C ({coldest.get('weather_description', '')})")
            
            windiest = analytics_data.get("windiest")
            if windiest:
                # Желтый для самого ветреного
                st.warning(f"**Самый ветреный день:** {windiest['date']} — {windiest['value']} м/с ({windiest.get('weather_description', '')})")