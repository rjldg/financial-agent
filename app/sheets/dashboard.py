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
from gspread.exceptions import WorksheetNotFound  # noqa: E402

from app.sheets.client import MONEY_PATTERN, batch_update, get_spreadsheet  # noqa: E402
from app.sheets.transactions import get_monthly_summary, list_monthly_sheets  # noqa: E402


def _get_or_create_hidden_index():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(INDEX_SHEET)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=INDEX_SHEET, rows=200, cols=5)
        ws.update("A1:E1", [INDEX_HEADERS], value_input_option="USER_ENTERED")
        batch_update([{
            "updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True},
                "fields": "hidden",
            }
        }])
    return ws


def rebuild_index() -> tuple[
    list[tuple[str, float, float, float, float]],
    dict[str, "MonthlySummary"],
]:
    """Recompute the entire _MonthlyIndex from every monthly tab.

    Returns (index_rows, summaries_by_month) so callers can reuse the
    summaries without a second round-trip to the Sheets API.
    """
    from app.models import MonthlySummary  # noqa: F811 (used in type hint above)

    summaries: dict[str, MonthlySummary] = {}
    totals: list[tuple[str, float, float]] = []
    for ym in list_monthly_sheets():
        s = get_monthly_summary(ym)
        summaries[ym] = s
        totals.append((ym, s.total_income, s.total_expenses))
    rows = compute_index_rows(totals)
    ws = _get_or_create_hidden_index()
    ws.batch_clear(["A2:E1000"])
    if rows:
        ws.update(f"A2:E{len(rows) + 1}", [list(r) for r in rows],
                  value_input_option="USER_ENTERED")
    return rows, summaries


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
    except WorksheetNotFound:
        dash = ss.add_worksheet(title=DASHBOARD_SHEET, rows=60, cols=12)
    batch_update([{
        "updateSheetProperties": {
            "properties": {"sheetId": dash.id, "index": 0},
            "fields": "index",
        }
    }])


def _ytd_category_totals_from_cache(
    summaries: dict[str, "MonthlySummary"], year: int
) -> dict[str, float]:
    """Sum expense-side category spend using pre-fetched summaries."""
    from collections import defaultdict
    acc: dict[str, float] = defaultdict(float)
    for ym, s in summaries.items():
        if not ym.startswith(f"{year}-"):
            continue
        for cat, total in s.category_totals.items():
            if cat != "Salary":
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

    rows, summaries = rebuild_index()
    ytd = ytd_totals(rows, year)
    cats = top_categories(_ytd_category_totals_from_cache(summaries, year), limit=5)

    ss = get_spreadsheet()
    ensure_core_tabs()
    dash = ss.worksheet(DASHBOARD_SHEET)
    sid = dash.id
    dash.clear()

    # --- Remove any pre-existing charts so rebuilds don't stack duplicates ---
    try:
        meta = ss.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId),charts)"}
        )
        del_reqs: list[dict] = []
        for sh in meta.get("sheets", []):
            if sh.get("properties", {}).get("sheetId") == sid:
                for chart in sh.get("charts", []):
                    del_reqs.append({"deleteEmbeddedObject": {
                        "objectId": chart["chartId"]}})
        if del_reqs:
            batch_update(del_reqs)
            logger.info("Deleted %d existing dashboard chart(s)", len(del_reqs))
    except Exception:
        logger.exception("Chart cleanup failed (non-fatal, continuing rebuild)")

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
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": MONEY_PATTERN}}},
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

    # --- Column widths so values don't get cut off ---
    col_widths = [
        # A-D: YTD cards & top spending
        (0, 1, 180),   # A – labels ("YTD Income", category names)
        (1, 2, 160),   # B – labels / values
        (2, 3, 160),   # C – values
        (3, 4, 160),   # D – values
        # E: spacer
        (4, 5, 30),
        # F-G: Subscriptions
        (5, 6, 220),   # F – subscription name + date
        (6, 7, 140),   # G – amount
        # H: spacer
        (7, 8, 30),
        # I-K: Budgets
        (8, 9, 160),   # I – category
        (9, 10, 140),  # J – spent
        (10, 11, 140), # K – limit
    ]
    for c0, c1, px in col_widths:
        reqs.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sid,
                    "dimension": "COLUMNS",
                    "startIndex": c0,
                    "endIndex": c1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

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
                                     {"type": "NUMBER", "pattern": MONEY_PATTERN}}},
                            "fields": "userEnteredFormat.numberFormat"}},
        ])
    except Exception:
        logger.exception("Upcoming-subscriptions dashboard block failed (non-fatal)")

    # --- Budget status (current month), placed in columns I:K ---
    try:
        from datetime import datetime as _dt2
        from app.sheets.budgets import get_budgets, budget_status
        ym = _dt2.now(tz=TZ).strftime("%Y-%m")
        limits = get_budgets()
        spent = get_monthly_summary(ym).category_totals if limits else {}
        block = [["Budget Status", "Spent", "Limit"]]
        for s in budget_status(spent, limits):
            block.append([s.category, s.spent, s.limit])
        if len(block) == 1:
            block.append(["(no budgets set)", "", ""])
        dash.update("I4", block, value_input_option="USER_ENTERED")
        batch_update([
            theme.solid_fill(sid, 3, 4, 8, 11, theme.COLORS["header"],
                             text=theme.COLORS["white"], bold=True),
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 4,
                                      "endRowIndex": 4 + len(block), "startColumnIndex": 9,
                                      "endColumnIndex": 11},
                            "cell": {"userEnteredFormat": {"numberFormat":
                                     {"type": "NUMBER", "pattern": MONEY_PATTERN}}},
                            "fields": "userEnteredFormat.numberFormat"}},
        ])
    except Exception:
        logger.exception("Budget-status dashboard block failed (non-fatal)")
