
# Система управления внутренними регламентами (база знаний)

**Роль проекта:** Продемонстрировать навыки системного анализа: сбор требований, моделирование, нефункциональные требования, проектирование БД, UI/UX макетирование, написание тест-кейсов.

## Проблема и решение
В компании много разрозненных инструкций (Word, PDF, email). Сотрудники тратят 15+ минут на поиск актуальной версии. Нет контроля утверждения.

Создать единое хранилище документов с версионированием, поиском, ролями и базовой аналитикой.

## Ключевые артефакты

| Артефакт | Описание | Ссылка |
|----------|----------|--------|
| Vision & Scope | Границы системы и цели | [01_vision_and_scope.md](docs/01_vision_and_scope.md) |
| Use Case Diagram | Диаграмма актёров и прецедентов | [use_case_diagram.png](images/use_case_diagram.png) |
| User Stories | 4 пользовательских истории с критериями приёмки | [03_user_stories.md](docs/03_user_stories.md) |
| Нефункциональные требования | Производительность, безопасность, удобство | [04_nonfunctional_reqs.md](docs/04_nonfunctional_reqs.md) |
| Модель данных (SQL) | DDL для PostgreSQL + ER-диаграмма | [05_data_model.sql](docs/05_data_model.sql) и [er_diagram.png](images/er_diagram.png) |
| Wireframes | Макеты главной, карточки документа, редактирования | [wireframe1](images/wireframe1.png), [wireframe2](images/wireframe2.png), [wireframe3](images/wireframe3.png)
| Тест-кейсы | Acceptance test для создания версии | [07_test_cases.md](docs/07_test_cases.md) |

## Инструменты
- Draw.io (диаграммы, wireframes)
- Markdown + GitHub
- PostgreSQL (только схема, без развёртывания)