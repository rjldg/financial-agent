from app.insights import compose_query_answer, compose_insights, row_matches
from app.models import MonthlySummary


def _summary():
    s = MonthlySummary(year_month="2026-03")
    s.total_income = 48000
    s.total_expenses = 12350
    s.net_savings = 35650
    s.transaction_count = 8
    s.category_totals = {"Salary": 48000, "Food": 1200, "Transport": 500}
    return s


def test_query_spend_category():
    assert compose_query_answer(_summary(), "spend", "Food", "2026-03") == \
        "You spent ₱1,200.00 on Food in 2026-03."


def test_query_spend_total():
    assert "₱12,350.00" in compose_query_answer(_summary(), "spend", None, "2026-03")


def test_query_income_net_count():
    assert "₱48,000.00" in compose_query_answer(_summary(), "income", None, "2026-03")
    assert "₱35,650.00" in compose_query_answer(_summary(), "net", None, "2026-03")
    assert "8" in compose_query_answer(_summary(), "count", None, "2026-03")


def test_query_count_with_category_uses_category_count_not_total():
    # 3 of the 10 total rows are Transport; the answer must say 3, not the overall total of 10.
    s = _summary()
    s.transaction_count = 10
    s.category_counts = {"Salary": 1, "Food": 6, "Transport": 3}
    answer = compose_query_answer(s, "count", "Transport", "2026-03")
    assert answer == "You logged 3 Transport transactions in 2026-03."
    assert "10" not in answer


def test_query_count_with_category_no_rows_returns_zero():
    s = _summary()
    s.category_counts = {"Salary": 1, "Food": 6, "Transport": 3}
    answer = compose_query_answer(s, "count", "Health", "2026-03")
    assert answer == "You logged 0 Health transactions in 2026-03."


def test_query_count_without_category_is_unchanged():
    s = _summary()
    s.category_counts = {"Salary": 1, "Food": 6, "Transport": 3}
    answer = compose_query_answer(s, "count", None, "2026-03")
    assert answer == "You logged 8 transactions in 2026-03."


def test_insights_reports_top_and_mom():
    cur = _summary()
    prev = MonthlySummary(year_month="2026-02")
    prev.total_expenses = 10000
    text = compose_insights(cur, prev)
    assert "Food" in text and "2026-02" in text


def test_row_matches_is_case_insensitive():
    assert row_matches("Grab home", "Transport", "grab")
    assert row_matches("McDo", "Food", "food")
    assert not row_matches("Salary", "Salary", "netflix")
