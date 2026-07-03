from datetime import date

import pytest

from app.sheets.subscriptions import (
    clamp_day, next_due_date, due_dates_since, parse_addsub_args,
)


def test_clamp_day_handles_short_months():
    assert clamp_day(2026, 2, 31) == 28   # Feb non-leap
    assert clamp_day(2028, 2, 31) == 29   # Feb leap
    assert clamp_day(2026, 4, 31) == 30   # April
    assert clamp_day(2026, 1, 15) == 15


def test_next_due_monthly_advances_a_month_when_already_charged():
    assert next_due_date(date(2026, 3, 1), "Monthly", 1) == date(2026, 4, 1)


def test_next_due_monthly_same_month_when_day_still_ahead():
    assert next_due_date(date(2026, 3, 1), "Monthly", 5) == date(2026, 3, 5)


def test_next_due_monthly_clamps_end_of_month():
    assert next_due_date(date(2026, 1, 31), "Monthly", 31) == date(2026, 2, 28)


def test_next_due_yearly():
    assert next_due_date(date(2025, 6, 15), "Yearly", 15, 6) == date(2026, 6, 15)


def test_due_dates_since_collects_missed_periods():
    dues = due_dates_since(date(2026, 3, 1), date(2026, 5, 15), "Monthly", 1)
    assert dues == [date(2026, 4, 1), date(2026, 5, 1)]


def test_due_dates_since_brand_new_returns_empty():
    # last_charged == today (set at add-time) => nothing due yet
    dues = due_dates_since(date(2026, 3, 10), date(2026, 3, 10), "Monthly", 1)
    assert dues == []


def test_parse_addsub_monthly():
    got = parse_addsub_args(["Netflix", "549", "Entertainment", "monthly", "day=1"])
    assert got == {"name": "Netflix", "amount": 549.0, "category": "Entertainment",
                   "type": "Expense", "frequency": "Monthly", "day": 1, "month": None}


def test_parse_addsub_yearly_with_type():
    got = parse_addsub_args(["iCloud", "1490", "Utilities", "yearly", "month=6", "day=15"])
    assert got["frequency"] == "Yearly" and got["month"] == 6 and got["day"] == 15


def test_parse_addsub_requires_day():
    with pytest.raises(ValueError):
        parse_addsub_args(["X", "10", "Food", "monthly"])


def test_parse_addsub_yearly_requires_month():
    with pytest.raises(ValueError):
        parse_addsub_args(["X", "10", "Food", "yearly", "day=1"])
