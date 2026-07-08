from datetime import date

from app.scheduler import filter_recent_expense, compose_weekly_digest


def _records():
    return [
        {"Date": "2026-03-20 09:00", "Description": "McDo", "Category": "Food", "Amount": 150, "Type": "Expense"},
        {"Date": "2026-03-18 09:00", "Description": "Grab", "Category": "Transport", "Amount": 90, "Type": "Expense"},
        {"Date": "2026-03-01 09:00", "Description": "Salary", "Category": "Salary", "Amount": 48000, "Type": "Income"},
        {"Date": "2026-03-10 09:00", "Description": "Old", "Category": "Food", "Amount": 999, "Type": "Expense"},
    ]


def test_filter_recent_expense_within_window():
    total, by_cat = filter_recent_expense(_records(), date(2026, 3, 21), days=7)
    assert total == 240  # 150 + 90 only; salary excluded, old expense out of window
    assert by_cat == {"Food": 150, "Transport": 90}


def test_compose_weekly_digest_mentions_total_and_upcoming():
    text = compose_weekly_digest(
        240.0, {"Food": 150, "Transport": 90},
        [("Netflix", 549.0, date(2026, 3, 25))], date(2026, 3, 21),
    )
    assert "₱240.00" in text and "Netflix" in text and "2026-03-21" in text
