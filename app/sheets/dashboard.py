"""Hidden _MonthlyIndex aggregate sheet + 📊 Dashboard tab.

Pure aggregation functions live at the top (unit-tested); Sheets I/O below.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

INDEX_SHEET = "_MonthlyIndex"
DASHBOARD_SHEET = "📊 Dashboard"
INDEX_HEADERS = ["Month", "Income", "Expense", "Net", "Running"]


def compute_index_rows(
    totals: list[tuple[str, float, float]]
) -> list[tuple[str, float, float, float, float]]:
    """Given (month, income, expense) tuples, return rows sorted by month with
    net (=income-expense) and cumulative running balance appended."""
    rows: list[tuple[str, float, float, float, float]] = []
    running = 0.0
    for month, income, expense in sorted(totals, key=lambda t: t[0]):
        net = income - expense
        running += net
        rows.append((month, income, expense, net, running))
    return rows


def ytd_totals(
    index_rows: list[tuple[str, float, float, float, float]], year: int
) -> dict[str, float]:
    """Year-to-date income/expense/net for `year`; running = last row overall."""
    prefix = f"{year}-"
    income = sum(r[1] for r in index_rows if r[0].startswith(prefix))
    expense = sum(r[2] for r in index_rows if r[0].startswith(prefix))
    running = index_rows[-1][4] if index_rows else 0.0
    return {"income": income, "expense": expense, "net": income - expense, "running": running}


def top_categories(totals: dict[str, float], *, limit: int = 5) -> list[tuple[str, float]]:
    """Return the highest-spend categories (descending), capped at `limit`."""
    return sorted(totals.items(), key=lambda kv: -kv[1])[:limit]
