"""Форматирование значений для интерфейса: чистые функции без Streamlit.

Метки направлений и инициатора дублируют значения справочников (PM-03: значения
выбираются по code). Значения фиксированы, поэтому словари уместны.
"""
from typing import Any

INITIATOR_LABELS: dict[str, str] = {
    "applicant": "Я откликнулся",
    "employer": "Работодатель написал первым",
}

DIRECTION_LABELS: dict[str, str] = {
    "SA_BA": "Системный / бизнес-аналитик",
    "TW": "Технический писатель",
}


def format_date(value: Any) -> str:
    """Дата в формате ДД.ММ.ГГГГ (NFR-06) или пустая строка."""
    if value is None:
        return ""
    return f"{value:%d.%m.%Y}"


def direction_label(code: str) -> str:
    return DIRECTION_LABELS.get(code, code)


def initiator_label(code: str) -> str:
    return INITIATOR_LABELS.get(code, code)


def format_next_stage(date_value: Any, name: str | None) -> str:
    """Ближайший запланированный этап одной строкой; «нет», если его нет."""
    if date_value is None or not name:
        return "нет"
    return f"{format_date(date_value)} — {name}"


def _money(value: int) -> str:
    """Целое с разделителем разрядов — неразрывный пробел как в русской типографике."""
    return f"{value:,}".replace(",", "\u00a0")


def format_salary(salary_from: int | None, salary_to: int | None) -> str:
    """Вилка «на руки», рубли; возможно одно значение (D15)."""
    if salary_from is None and salary_to is None:
        return "не указана"
    if salary_from is not None and salary_to is not None:
        if salary_from == salary_to:
            return f"{_money(salary_from)} ₽"
        return f"{_money(salary_from)} — {_money(salary_to)} ₽"
    if salary_from is not None:
        return f"от {_money(salary_from)} ₽"
    return f"до {_money(salary_to)} ₽"