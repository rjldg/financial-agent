"""Google Sheets integration via gspread and a service-account key.

Features:
- Monthly worksheets — a new tab (e.g. "2026-03") is created automatically
  the first time a transaction is logged in that month.
- Each monthly sheet includes headers and live summary formulas
  (Total Income, Total Expenses, Net Savings, per-category breakdown).
- A ``get_monthly_summary()`` function reads raw data and returns computed
  metrics that the Telegram bot can display.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import gspread
from gspread.exceptions import APIError, WorksheetNotFound

from app.config import GOOGLE_SHEETS_CREDENTIALS_FILE, SHEET_ID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEADERS = ["Date", "Description", "Category", "Amount", "Type"]

# Known categories for the formula-based breakdown (columns G–H).
# Transactions with unlisted categories still get recorded; they just won't
# appear in the in-sheet formula section (but *will* show in /summary).
_FORMULA_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Salary",
    "Entertainment",
    "Shopping",
    "Health",
    "Utilities",
    "Rent",
    "Freelance",
    "Dating",
    "Other",
]

# ---------------------------------------------------------------------------
# Spreadsheet client (lazy singleton)
# ---------------------------------------------------------------------------

_spreadsheet: gspread.Spreadsheet | None = None


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet
    if _spreadsheet is None:
        gc = gspread.service_account(filename=GOOGLE_SHEETS_CREDENTIALS_FILE)
        _spreadsheet = gc.open_by_key(SHEET_ID)
        logger.info("Connected to Google Sheet: %s", _spreadsheet.title)
    return _spreadsheet


def _invalidate() -> None:
    """Reset cached handles so the next call re-authenticates."""
    global _spreadsheet
    _spreadsheet = None


# ---------------------------------------------------------------------------
# Monthly worksheet helpers
# ---------------------------------------------------------------------------


def _get_or_create_monthly_sheet(year_month: str) -> gspread.Worksheet:
    """Return the worksheet for *year_month* (e.g. ``"2026-03"``).

    If the sheet doesn't exist yet it is created with headers in row 1
    and live summary formulas in columns G–H.
    """
    ss = _get_spreadsheet()
    try:
        return ss.worksheet(year_month)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=year_month, rows=500, cols=10)
        _setup_headers_and_formulas(ws)
        logger.info("Created new monthly sheet: %s", year_month)
        return ws


def _setup_headers_and_formulas(ws: gspread.Worksheet) -> None:
    """Populate row 1 headers (A–E) and summary formulas (G–H)."""

    # --- Data headers (A1:E1) ---
    ws.update("A1:E1", [_HEADERS], value_input_option="USER_ENTERED")
    ws.format("A1:E1", {"textFormat": {"bold": True}})

    # --- Summary block (G:H) ---
    summary_cells: list[list[str]] = [
        ["Metric", "Value"],
        ["Total Income", '=SUMIFS(D:D,E:E,"Income")'],
        ["Total Expenses", '=SUMIFS(D:D,E:E,"Expense")'],
        ["Net Savings", "=H2-H3"],
        [],  # blank separator
        ["Category Breakdown", ""],
    ]

    # One row per known category: =SUMIF(C:C,"Food",D:D)
    for cat in _FORMULA_CATEGORIES:
        summary_cells.append([cat, f'=SUMIF(C:C,"{cat}",D:D)'])

    end_row = len(summary_cells)
    ws.update(
        f"G1:H{end_row}",
        summary_cells,
        value_input_option="USER_ENTERED",
    )
    ws.format("G1:H1", {"textFormat": {"bold": True}})
    ws.format("G6:G6", {"textFormat": {"bold": True}})


# ---------------------------------------------------------------------------
# Public API — append
# ---------------------------------------------------------------------------


def append_transaction(
    date: str,
    description: str,
    category: str,
    amount: float,
    txn_type: str,
) -> None:
    """Append a transaction row to the monthly worksheet.

    The worksheet is determined by the first 7 characters of *date*
    (``YYYY-MM``).  If the sheet doesn't exist yet it is created.

    Column order: Date | Description | Category | Amount | Type

    Raises :class:`gspread.exceptions.APIError` on quota / network issues.
    """
    year_month = date[:7]  # "2026-03-20 14:05" → "2026-03"
    try:
        ws = _get_or_create_monthly_sheet(year_month)
        # Find the next empty row in column A (data area) so we don't
        # accidentally land below the summary formulas in columns G–H.
        col_a = ws.col_values(1)  # all values in column A
        next_row = len(col_a) + 1
        ws.update(
            f"A{next_row}:E{next_row}",
            [[date, description, category, amount, txn_type]],
            value_input_option="USER_ENTERED",
        )
    except APIError:
        _invalidate()
        raise


# ---------------------------------------------------------------------------
# Public API — summary
# ---------------------------------------------------------------------------


@dataclass
class MonthlySummary:
    """Computed financial summary for a single month."""

    year_month: str
    total_income: float = 0.0
    total_expenses: float = 0.0
    net_savings: float = 0.0
    category_totals: dict[str, float] = field(default_factory=dict)
    transaction_count: int = 0


def get_monthly_summary(year_month: str) -> MonthlySummary:
    """Read all rows from the *year_month* sheet and compute summary metrics.

    Returns a :class:`MonthlySummary` dataclass.
    Raises ``WorksheetNotFound`` if there are no transactions for that month.
    """
    ss = _get_spreadsheet()
    ws = ss.worksheet(year_month)  # raises WorksheetNotFound

    rows = ws.get_all_records(expected_headers=_HEADERS)

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
    return summary


def list_monthly_sheets() -> list[str]:
    """Return a sorted list of existing monthly worksheet titles (e.g. ``["2026-01", "2026-03"]``)."""
    ss = _get_spreadsheet()
    names: list[str] = []
    for ws in ss.worksheets():
        # Only include sheets that look like YYYY-MM
        title = ws.title
        if len(title) == 7 and title[4] == "-" and title[:4].isdigit() and title[5:].isdigit():
            names.append(title)
    return sorted(names)
