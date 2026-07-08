"""Budgets tab: pure alert/status math + Sheets CRUD."""
from __future__ import annotations

import logging

from app.formatting import format_money
from app.models import BudgetStatus

logger = logging.getLogger(__name__)

BUDGETS_SHEET = "🎯 Budgets"
BUDGETS_HEADERS = ["Category", "MonthlyLimit"]


def format_budget_alert(category: str, spent: float, limit: float, threshold: float) -> str | None:
    """Return a warning string if spend has reached `threshold` of `limit`, else None."""
    if not limit:
        return None
    ratio = spent / limit
    pct = round(ratio * 100)
    if ratio >= 1.0:
        return (f"⚠ {category} over budget: {format_money(spent)} / "
                f"{format_money(limit)} ({pct}%)")
    if ratio >= threshold:
        return f"⚠ {category} at {pct}% of {format_money(limit)} budget"
    return None


def budget_status(spent_by_cat: dict[str, float], limits: dict[str, float]) -> list[BudgetStatus]:
    """BudgetStatus per category that has a limit, sorted by ratio descending."""
    out = [BudgetStatus(category=cat, spent=spent_by_cat.get(cat, 0.0), limit=limit)
           for cat, limit in limits.items()]
    return sorted(out, key=lambda s: -s.ratio)


# --- Sheets I/O ---
from app.sheets.client import get_spreadsheet  # noqa: E402


def ensure_budgets_tab():
    ss = get_spreadsheet()
    try:
        return ss.worksheet(BUDGETS_SHEET)
    except Exception:
        ws = ss.add_worksheet(title=BUDGETS_SHEET, rows=50, cols=2)
        ws.update("A1", [BUDGETS_HEADERS], value_input_option="USER_ENTERED")
        return ws


def get_budgets() -> dict[str, float]:
    ws = ensure_budgets_tab()
    out: dict[str, float] = {}
    for row in ws.get_all_values()[1:]:
        if row and row[0].strip():
            try:
                out[row[0].strip()] = float(row[1] or 0)
            except (ValueError, IndexError):
                continue
    return out


def set_budget(category: str, limit: float) -> None:
    ws = ensure_budgets_tab()
    for i, row in enumerate(ws.get_all_values()[1:], start=2):
        if row and row[0].strip().lower() == category.lower():
            ws.update_cell(i, 2, limit)
            return
    ws.append_row([category, limit], value_input_option="USER_ENTERED")


def budget_alert_for(category: str, year_month: str) -> str | None:
    """Read the month's spend for `category` and return an alert if over threshold."""
    from app.config import BUDGET_ALERT_THRESHOLD
    from app.sheets.transactions import get_monthly_summary
    limit = get_budgets().get(category)
    if not limit:
        return None
    spent = get_monthly_summary(year_month).category_totals.get(category, 0.0)
    return format_budget_alert(category, spent, limit, BUDGET_ALERT_THRESHOLD)
