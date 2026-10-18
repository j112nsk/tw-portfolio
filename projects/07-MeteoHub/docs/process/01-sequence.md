# Sequence-диаграмма: запрос прогноза

| | |
|---|---|
| Версия | 1.0 |
| Дата | 18.10.2026 |
| Автор | Юрий Савиных |
| Статус | Утверждён автором |
| Связанные документы | [Руководство разработчика](../user-docs/05-developer-guide.md), [ER-диаграмма](../data-model/01-er-diagram.md) |

## 1. Назначение документа

Документ описывает последовательность взаимодействия компонентов системы при запросе прогноза погоды. Диаграмма демонстрирует логику работы кэша и процесса агрегации данных.

## 2. Диаграмма последовательности (сценарий кэш-промаха)

```mermaid
sequenceDiagram
    autonumber
    actor User as Пользователь (UI)
    participant API as FastAPI (/forecast)
    participant Cache as Cache Service
    participant DB as PostgreSQL
    participant MET as MET Norway API

    User->>API: GET /forecast?city=Москва
    API->>DB: Проверка геокодинга (geocode_cache)
    DB-->>API: Координаты (Cache Hit)
    
    API->>Cache: get_or_fetch_met_forecast(lat, lon)
    Cache->>DB: SELECT payload FROM weather_cache
    DB-->>Cache: Пусто (Cache Miss)
    
    Cache->>MET: GET /weatherapi/locationforecast/2.0
    MET-->>Cache: GeoJSON (timeseries)
    
    Cache->>DB: INSERT INTO weather_cache (Сырой JSON)
    
    Cache->>Cache: extract_daily(GeoJSON)
    Cache->>DB: UPSERT INTO weather_daily (Дневные агрегаты)
    
    Cache-->>API: Сырой JSON
    API->>API: extract_hourly(), extract_daily()
    API-->>User: 200 OK (JSON ответ)
```

## 3. Описание шагов

1. **Запрос пользователя:** UI отправляет GET-запрос с названием города.
2. **Разрешение города:** API обращается к кэшу (или Nominatim), чтобы получить координаты.
3. **Проверка кэша погоды:** API просит сервис кэша найти прогноз по координатам. Если запись есть и не истекла (Cache Hit) — данные сразу возвращаются.
4. **Запрос к внешнему API (Cache Miss):** Если данных нет, сервис обращается к MET Norway.
5. **Сохранение:** Сырой ответ сохраняется в `weather_cache`.
6. **Агрегация:** Попутно данные пересчитываются в дневные показатели и сохраняются в `weather_daily` для последующей аналитики.
7. **Ответ:** API форматирует данные и возвращает пользователю.

## 4. Журнал изменений

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 18.10.2026 | Первая версия: описан сценарий с кэш-промахом. |