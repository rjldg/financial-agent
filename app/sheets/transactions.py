"""Monthly transaction worksheets: create, append, summarize, list."""
from __future__ import annotations

import logging
from collections import defaultdict

from gspread.exceptions import APIError, WorksheetNotFound

from app.models import MonthlySummary
from app.sheets import theme
from app.sheets.client import (
    batch_update, fmt_bold, get_spreadsheet, grid_range, invalidate, num_fmt,
)

logger = logging.getLogger(__name__)

HEADERS = ["Date", "Description", "Category", "Amount", "Type"]

FORMULA_CATEGORIES = [
    "Food", "Transport", "Bills", "Salary", "Entertainment", "Shopping",
    "Health", "Utilities", "Rent", "Freelance", "Dating", "Other",
]


def _previous_month(year_month: str) -> str:
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def get_or_create_monthly_sheet(year_month: str):
    ss = get_spreadsheet()
    try:
        return ss.worksheet(year_month)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=year_month, rows=500, cols=16)
        _setup_headers_and_formulas(ws, year_month)
        logger.info("Created new monthly sheet: %s", year_month)
        return ws


def _setup_headers_and_formulas(ws, year_month: str) -> None:
    prev = _previous_month(year_month)
    ws.update("A1:E1", [HEADERS], value_input_option="USER_ENTERED")
    summary_cells: list[list[str]] = [
        ["Metric", "Value"],
        ["Total Income", '=SUMIFS(D:D,E:E,"Income")'],
        ["Total Expenses", '=SUMIFS(D:D,E:E,"Expense")'],
        ["Net Savings", "=H2-H3"],
        [],
        ["Carried Forward", f"=IFERROR('{prev}'!H7,0)"],
        ["Running Total", "=H6+H4"],
        [],
        ["Category Breakdown", ""],
    ]
    cat_start_0 = len(summary_cells)
    for cat in FORMULA_CATEGORIES:
        summary_cells.append([cat, f'=SUMIF(C:C,"{cat}",D:D)'])
    cat_end_0 = len(summary_cells)
    ws.update(f"G1:H{cat_end_0}", summary_cells, value_input_option="USER_ENTERED")

    sid = ws.id
    requests: list[dict] = [
        fmt_bold(sid, 0, 1, 0, 5),
        fmt_bold(sid, 0, 1, 6, 8),
        fmt_bold(sid, 5, 7, 6, 7),
        fmt_bold(sid, 8, 9, 6, 7),
        {"repeatCell": {"range": grid_range(sid, 1, 500, 3, 4),
                        "cell": num_fmt('"₱"#,##0.00'),
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": grid_range(sid, 1, cat_end_0, 7, 8),
                        "cell": num_fmt('"₱"#,##0.00'),
                        "fields": "userEnteredFormat.numberFormat"}},
        {"setDataValidation": {"range": grid_range(sid, 1, 500, 2, 3),
                               "rule": {"condition": {"type": "ONE_OF_LIST",
                                        "values": [{"userEnteredValue": c} for c in FORMULA_CATEGORIES]},
                                        "showCustomUi": True, "strict": False}}},
        {"setDataValidation": {"range": grid_range(sid, 1, 500, 4, 5),
                               "rule": {"condition": {"type": "ONE_OF_LIST",
                                        "values": [{"userEnteredValue": "Income"},
                                                   {"userEnteredValue": "Expense"}]},
                                        "showCustomUi": True, "strict": True}}},
        {"addChart": {"chart": {"spec": {"title": "By Category",
            "pieChart": {"legendPosition": "RIGHT_LEGEND",
                "domain": {"sourceRange": {"sources": [grid_range(sid, cat_start_0, cat_end_0, 6, 7)]}},
                "series": {"sourceRange": {"sources": [grid_range(sid, cat_start_0, cat_end_0, 7, 8)]}}}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": 0, "columnIndex": 9},
                "widthPixels": 500, "heightPixels": 300}}}}},
        {"addChart": {"chart": {"spec": {"title": "Income vs Expenses",
            "basicChart": {"chartType": "COLUMN", "legendPosition": "NO_LEGEND",
                "domains": [{"domain": {"sourceRange": {"sources": [grid_range(sid, 1, 3, 6, 7)]}}}],
                "series": [{"series": {"sourceRange": {"sources": [grid_range(sid, 1, 3, 7, 8)]}}}]}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": 16, "columnIndex": 9},
                "widthPixels": 500, "heightPixels": 300}}}}},
    ]
    requests += theme.monthly_theme_requests(sid)
    batch_update(requests)


def append_transaction(date: str, description: str, category: str,
                       amount: float, txn_type: str) -> int:
    year_month = date[:7]
    try:
        ws = get_or_create_monthly_sheet(year_month)
        col_a = ws.col_values(1)
        next_row = len(col_a) + 1
        ws.update(f"A{next_row}:E{next_row}",
                  [[date, description, category, amount, txn_type]],
                  value_input_option="USER_ENTERED")
        _reindex(year_month)
        return next_row
    except APIError:
        invalidate()
        raise


def get_monthly_summary(year_month: str) -> MonthlySummary:
    ss = get_spreadsheet()
    ws = ss.worksheet(year_month)
    rows = ws.get_all_records(expected_headers=HEADERS)
    summary = MonthlySummary(year_month=year_month)
    category_totals: dict[str, float] = defaultdict(float)
    for row in rows:
        try:
            amount = float(row["Amount"])
        except (ValueError, TypeError):
            continue
        txn_type = str(row.get("Type", "")).strip()
        category = str(row.get("Category", "Other")).strip()
        if txn_type == "Income":
            summary.total_income += amount
        elif txn_type == "Expense":
            summary.total_expenses += amount
        category_totals[category] += amount
        summary.transaction_count += 1
    summary.net_savings = summary.total_income - summary.total_expenses
    summary.category_totals = dict(sorted(category_totals.items(), key=lambda x: -x[1]))
    try:
        cf_val = ws.acell("H6", value_render_option="FORMATTED_VALUE").value
        summary.carried_forward = float(cf_val.replace(",", "")) if cf_val else 0.0
    except (ValueError, TypeError, AttributeError):
        pass
    try:
        rt_val = ws.acell("H7", value_render_option="FORMATTED_VALUE").value
        summary.running_total = float(rt_val.replace(",", "")) if rt_val else 0.0
    except (ValueError, TypeError, AttributeError):
        pass
    return summary


def list_monthly_sheets() -> list[str]:
    ss = get_spreadsheet()
    names: list[str] = []
    for ws in ss.worksheets():
        title = ws.title
        if len(title) == 7 and title[4] == "-" and title[:4].isdigit() and title[5:].isdigit():
            names.append(title)
    return sorted(names)


def _reindex(year_month: str) -> None:
    try:
        from app.sheets import dashboard  # local import breaks the cycle
        dashboard.update_month(year_month)
    except Exception:
        logger.exception("Index update failed (non-fatal) for %s", year_month)


def get_last_transaction(year_month: str):
    """Return (row_index, [Date, Description, Category, Amount, Type]) or None."""
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(year_month)
    except WorksheetNotFound:
        return None
    col_a = ws.col_values(1)
    if len(col_a) < 2:  # only the header
        return None
    row = len(col_a)
    vals = ws.get(f"A{row}:E{row}")
    return (row, vals[0] if vals else [])


def delete_transaction_row(year_month: str, row: int) -> None:
    ss = get_spreadsheet()
    ws = ss.worksheet(year_month)
    ws.delete_rows(row)
    _reindex(year_month)


def update_transaction_category(year_month: str, row: int, category: str) -> None:
    ss = get_spreadsheet()
    ws = ss.worksheet(year_month)
    ws.update_cell(row, 3, category)
    _reindex(year_month)


def toggle_transaction_type(year_month: str, row: int) -> str:
    ss = get_spreadsheet()
    ws = ss.worksheet(year_month)
    current = ws.cell(row, 5).value
    new_type = "Income" if current == "Expense" else "Expense"
    ws.update_cell(row, 5, new_type)
    _reindex(year_month)
    return new_type


def search_transactions(term: str, limit: int = 20) -> list[tuple]:
    """Scan monthly tabs newest-first, return rows whose desc/category matches `term`."""
    from app.insights import row_matches
    results: list[tuple] = []
    for ym in reversed(list_monthly_sheets()):
        ws = get_spreadsheet().worksheet(ym)
        for r in ws.get_all_records(expected_headers=HEADERS):
            desc, cat = str(r.get("Description", "")), str(r.get("Category", ""))
            if row_matches(desc, cat, term):
                results.append((ym, r.get("Date"), desc, cat, r.get("Amount"), r.get("Type")))
                if len(results) >= limit:
                    return results
    return results
