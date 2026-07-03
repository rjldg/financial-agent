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


def ensure_core_tabs() -> None:
    """Create the Dashboard + hidden index tabs if missing; pin Dashboard first."""
    ss = get_spreadsheet()
    _get_or_create_hidden_index()
    try:
        dash = ss.worksheet(DASHBOARD_SHEET)
    except Exception:
        dash = ss.add_worksheet(title=DASHBOARD_SHEET, rows=60, cols=12)
    batch_update([{
        "updateSheetProperties": {
            "properties": {"sheetId": dash.id, "index": 0},
            "fields": "index",
        }
    }])


def _ytd_category_totals(year: int) -> dict[str, float]:
    """Sum expense-side category spend across the year's monthly tabs."""
    from collections import defaultdict
    acc: dict[str, float] = defaultdict(float)
    for ym in list_monthly_sheets():
        if not ym.startswith(f"{year}-"):
            continue
        s = get_monthly_summary(ym)
        for cat, total in s.category_totals.items():
            if cat != "Salary":  # exclude the main income category from "spending"
                acc[cat] += total
    return dict(acc)


def rebuild_dashboard(year: int | None = None) -> None:
    """Recompute _MonthlyIndex, then repaint the Dashboard tab."""
    from datetime import datetime
    from app.config import TZ
    from app.formatting import format_money
    from app.sheets import theme

    if year is None:
        year = datetime.now(tz=TZ).year

    rows = rebuild_index()
    ytd = ytd_totals(rows, year)
    cats = top_categories(_ytd_category_totals(year), limit=5)

    ss = get_spreadsheet()
    ensure_core_tabs()
    dash = ss.worksheet(DASHBOARD_SHEET)
    sid = dash.id
    dash.clear()

    # --- Values ---
    updated = datetime.now(tz=TZ).strftime("%Y-%m-%d %H:%M")
    grid: list[list] = [["💰 Finance Overview", "", "", ""]]
    grid.append([f"Year to date · {year}", f"updated {updated}", "", ""])
    grid.append([])                                              # row 3 spacer
    grid.append(["YTD Income", "YTD Expenses", "YTD Net", "Running Balance"])  # row 4 labels
    grid.append([ytd["income"], ytd["expense"], ytd["net"], ytd["running"]])   # row 5 values
    grid.append([])
    grid.append(["Top Spending (YTD)", ""])                     # row 7
    for cat, amt in cats:
        grid.append([cat, amt])
    dash.update("A1", grid, value_input_option="USER_ENTERED")

    # --- Formatting ---
    reqs: list[dict] = [
        theme.solid_fill(sid, 0, 1, 0, 4, theme.COLORS["ink"], text=theme.COLORS["white"], bold=True),
        theme.solid_fill(sid, 3, 4, 0, 1, theme.COLORS["card_income"], text=theme.COLORS["white"], bold=True),
        theme.solid_fill(sid, 3, 4, 1, 2, theme.COLORS["card_expense"], text=theme.COLORS["white"], bold=True),
        theme.solid_fill(sid, 3, 4, 2, 3, theme.COLORS["card_net"], text=theme.COLORS["white"], bold=True),
        theme.solid_fill(sid, 3, 4, 3, 4, theme.COLORS["card_running"], text=theme.COLORS["white"], bold=True),
        theme.solid_fill(sid, 4, 5, 0, 4, theme.COLORS["band"], bold=True),
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 4, "endRowIndex": 5,
                                  "startColumnIndex": 0, "endColumnIndex": 4},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": '"₱"#,##0.00'}}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]

    # --- 12-month trend chart from _MonthlyIndex ---
    idx = ss.worksheet(INDEX_SHEET)
    iid = idx.id
    n = len(rows)
    start = max(1, n - 11)  # last 12 data rows (index rows begin at sheet row 2 => index 1)
    reqs.append({"addChart": {"chart": {"spec": {
        "title": "12-Month Income vs Expenses",
        "basicChart": {
            "chartType": "COLUMN", "legendPosition": "BOTTOM_LEGEND",
            "domains": [{"domain": {"sourceRange": {"sources": [
                {"sheetId": iid, "startRowIndex": start, "endRowIndex": n + 1,
                 "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
            "series": [
                {"series": {"sourceRange": {"sources": [
                    {"sheetId": iid, "startRowIndex": start, "endRowIndex": n + 1,
                     "startColumnIndex": 1, "endColumnIndex": 2}]}}},
                {"series": {"sourceRange": {"sources": [
                    {"sheetId": iid, "startRowIndex": start, "endRowIndex": n + 1,
                     "startColumnIndex": 2, "endColumnIndex": 3}]}}},
            ],
        }},
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sid, "rowIndex": 14, "columnIndex": 0},
            "widthPixels": 620, "heightPixels": 300}}}}})

    batch_update(reqs)

    # --- Upcoming subscriptions (next 30 days), placed in columns F:G ---
    try:
        from datetime import datetime as _dt
        from app.sheets.subscriptions import upcoming_subscriptions
        today = _dt.now(tz=TZ).date()
        upcoming = upcoming_subscriptions(today, days=30)
        block = [["Upcoming Subscriptions", ""]]
        for s, when in upcoming:
            block.append([f"{s.name} · {when.isoformat()}", s.amount])
        if len(block) == 1:
            block.append(["(none in next 30 days)", ""])
        dash.update("F4", block, value_input_option="USER_ENTERED")
        batch_update([
            theme.solid_fill(sid, 3, 4, 5, 7, theme.COLORS["header"],
                             text=theme.COLORS["white"], bold=True),
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 4,
                                      "endRowIndex": 4 + len(block), "startColumnIndex": 6,
                                      "endColumnIndex": 7},
                            "cell": {"userEnteredFormat": {"numberFormat":
                                     {"type": "NUMBER", "pattern": '"₱"#,##0.00'}}},
                            "fields": "userEnteredFormat.numberFormat"}},
        ])
    except Exception:
        logger.exception("Upcoming-subscriptions dashboard block failed (non-fatal)")
