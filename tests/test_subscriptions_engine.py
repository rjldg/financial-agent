from datetime import date

import pytest

from app.sheets.subscriptions import (
    clamp_day, initial_last_charged, next_due_date, due_dates_since, parse_addsub_args,
)


def test_clamp_day_handles_short_months():
    assert clamp_day(2026, 2, 31) == 28   # Feb non-leap
    assert clamp_day(2028, 2, 31) == 29   # Feb leap
    assert clamp_day(2026, 4, 31) == 30   # April
    assert clamp_day(2026, 1, 15) == 15


def test_next_due_monthly_advances_a_month_when_already_charged():
    assert next_due_date(date(2026, 3, 1), "Monthly", 1) == date(2026, 4, 1)


def test_next_due_monthly_never_lands_in_the_charged_month():
    # Was date(2026, 3, 5) before the one-charge-per-month guard. A same-month
    # result is what double-charged dental in July, so the engine now always
    # moves on. _initial_last_charged is what keeps a new subscription's first
    # charge on time - see test_a_new_subscription_still_charges_this_month.
    assert next_due_date(date(2026, 3, 1), "Monthly", 5) == date(2026, 4, 5)


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


# --- one charge per calendar month ---------------------------------------
# Moving a monthly subscription's day later in the month used to create a second
# due date in that same month, which really did double-charge a dental payment.

def test_moving_the_day_later_does_not_charge_twice_in_one_month():
    # Charged on the 20th, then the day setting is moved to 30.
    assert next_due_date(date(2026, 7, 20), "Monthly", 30) == date(2026, 8, 30)


def test_moving_the_day_earlier_still_waits_for_next_month():
    assert next_due_date(date(2026, 9, 25), "Monthly", 5) == date(2026, 10, 5)


def test_a_normal_month_is_unaffected():
    assert next_due_date(date(2026, 7, 20), "Monthly", 20) == date(2026, 8, 20)
    assert next_due_date(date(2026, 8, 6), "Monthly", 6) == date(2026, 9, 6)


def test_end_of_month_day_clamps_to_each_month_length():
    assert next_due_date(date(2026, 7, 31), "Monthly", 31) == date(2026, 8, 31)
    assert next_due_date(date(2026, 8, 31), "Monthly", 31) == date(2026, 9, 30)
    assert next_due_date(date(2027, 1, 31), "Monthly", 31) == date(2027, 2, 28)


def test_catch_up_after_a_gap_still_yields_one_date_per_month():
    due = due_dates_since(date(2026, 5, 31), date(2026, 8, 21), "Monthly", 31)
    assert due == [date(2026, 6, 30), date(2026, 7, 31)]


def test_yearly_is_untouched_by_the_monthly_guard():
    assert next_due_date(date(2026, 3, 1), "Yearly", 15, 6) == date(2026, 6, 15)
    assert next_due_date(date(2026, 8, 1), "Yearly", 15, 6) == date(2027, 6, 15)


# --- a new subscription's first charge must still land on time -------------

def test_a_new_subscription_still_charges_this_month():
    # Added on the 1st, pays on the 5th: the 5th is still ahead, so the marker
    # goes back a month and the first charge lands this month as before.
    marker = initial_last_charged(date(2026, 3, 1), 5)
    assert marker == date(2026, 2, 28)
    assert next_due_date(marker, "Monthly", 5) == date(2026, 3, 5)


def test_a_new_subscription_whose_day_has_passed_waits():
    marker = initial_last_charged(date(2026, 3, 10), 5)
    assert marker == date(2026, 3, 10)
    assert next_due_date(marker, "Monthly", 5) == date(2026, 4, 5)


def test_a_new_subscription_is_never_back_charged():
    today = date(2026, 3, 10)
    marker = initial_last_charged(today, 1)   # the 1st already went by
    assert due_dates_since(marker, today, "Monthly", 1) == []
