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


# --- Sheets I/O (append below the pure functions) ---
from app.sheets.client import batch_update, get_spreadsheet  # noqa: E402
from app.sheets.transactions import get_monthly_summary, list_monthly_sheets  # noqa: E402


def _get_or_create_hidden_index():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(INDEX_SHEET)
    except Exception:
        ws = ss.add_worksheet(title=INDEX_SHEET, rows=200, cols=5)
        ws.update("A1:E1", [INDEX_HEADERS], value_input_option="USER_ENTERED")
        batch_update([{
            "updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True},
                "fields": "hidden",
            }
        }])
    return ws


def rebuild_index() -> list[tuple[str, float, float, float, float]]:
    """Recompute the entire _MonthlyIndex from every monthly tab. Authoritative."""
    totals: list[tuple[str, float, float]] = []
    for ym in list_monthly_sheets():
        s = get_monthly_summary(ym)
        totals.append((ym, s.total_income, s.total_expenses))
    rows = compute_index_rows(totals)
    ws = _get_or_create_hidden_index()
    ws.batch_clear(["A2:E1000"])
    if rows:
        ws.update(f"A2:E{len(rows) + 1}", [list(r) for r in rows],
                  value_input_option="USER_ENTERED")
    return rows


def update_month(year_month: str) -> None:
    """Cheap upsert: recompute one month, rewrite index rows with fresh running."""
    ws = _get_or_create_hidden_index()
    existing = ws.get_all_values()[1:]  # skip header
    totals: dict[str, tuple[float, float]] = {}
    for r in existing:
        if r and r[0]:
            try:
                totals[r[0]] = (float(r[1] or 0), float(r[2] or 0))
            except ValueError:
                continue
    s = get_monthly_summary(year_month)
    totals[year_month] = (s.total_income, s.total_expenses)
    rows = compute_index_rows([(m, i, e) for m, (i, e) in totals.items()])
    ws.batch_clear(["A2:E1000"])
    if rows:
        ws.update(f"A2:E{len(rows) + 1}", [list(r) for r in rows],
                  value_input_option="USER_ENTERED")


def read_index_rows() -> list[tuple[str, float, float, float, float]]:
    ws = _get_or_create_hidden_index()
    out: list[tuple[str, float, float, float, float]] = []
    for r in ws.get_all_values()[1:]:
        if r and r[0]:
            try:
                out.append((r[0], float(r[1] or 0), float(r[2] or 0),
                            float(r[3] or 0), float(r[4] or 0)))
            except ValueError:
                continue
    return out
