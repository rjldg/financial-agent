# tests/test_models.py
from datetime import date

from app.models import CATEGORIES, Transaction, Subscription, BudgetStatus, MonthlySummary


def test_categories_has_twelve_entries():
    assert len(CATEGORIES) == 12
    assert "Food" in CATEGORIES and "Other" in CATEGORIES


def test_transaction_validates():
    t = Transaction(amount=150, category="Food", description="McDo", type="Expense")
    assert t.amount == 150.0 and t.type == "Expense"


def test_subscription_defaults():
    s = Subscription(
        name="Netflix", amount=549, category="Entertainment", type="Expense",
        frequency="Monthly", day=1, month=None, last_charged=date(2026, 3, 1), active=True,
    )
    assert s.notes == "" and s.row is None


def test_budget_status_ratio():
    b = BudgetStatus(category="Food", spent=4000, limit=5000)
    assert b.ratio == 0.8
    assert BudgetStatus(category="X", spent=10, limit=0).ratio == 0.0


def test_monthly_summary_defaults():
    m = MonthlySummary(year_month="2026-03")
    assert m.total_income == 0.0 and m.category_totals == {}
