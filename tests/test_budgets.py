from app.sheets.budgets import format_budget_alert, budget_status
from app.models import BudgetStatus


def test_alert_none_when_under_threshold():
    assert format_budget_alert("Food", 2000, 5000, 0.8) is None


def test_alert_when_at_or_over_threshold():
    msg = format_budget_alert("Food", 4000, 5000, 0.8)
    assert msg is not None and "Food" in msg and "80%" in msg


def test_alert_over_budget_wording():
    msg = format_budget_alert("Entertainment", 2600, 2000, 0.8)
    assert "over budget" in msg.lower() and "130%" in msg


def test_alert_zero_limit_is_none():
    assert format_budget_alert("Food", 100, 0, 0.8) is None


def test_budget_status_builds_sorted_list():
    statuses = budget_status({"Food": 4000, "Transport": 500}, {"Food": 5000, "Transport": 3000})
    assert all(isinstance(s, BudgetStatus) for s in statuses)
    # highest ratio first: Food 0.8 before Transport ~0.167
    assert statuses[0].category == "Food"


def test_budget_status_ignores_categories_without_limit():
    statuses = budget_status({"Food": 4000, "Misc": 999}, {"Food": 5000})
    assert [s.category for s in statuses] == ["Food"]
