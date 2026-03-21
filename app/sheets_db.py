"""Google Sheets integration via gspread and a service-account key.

Features:
- Monthly worksheets — a new tab (e.g. "2026-03") is created automatically
  the first time a transaction is logged in that month.
- Each monthly sheet includes headers, live summary formulas, a running
  balance carried forward from the previous month, category/type dropdowns,
  numeric formatting, and embedded charts.
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
# Internal helpers
# ---------------------------------------------------------------------------


def _previous_month(year_month: str) -> str:
    """Return the YYYY-MM string for the month preceding *year_month*."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _grid_range(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """Return a Sheets API GridRange dict (0-indexed, exclusive end)."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": r0,
        "endRowIndex": r1,
        "startColumnIndex": c0,
        "endColumnIndex": c1,
    }


def _fmt_bold(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """Return a ``repeatCell`` request that bolds a range."""
    return {
        "repeatCell": {
            "range": _grid_range(sheet_id, r0, r1, c0, c1),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }
    }


def _num_fmt(pattern: str) -> dict:
    """Return a CellData dict with a number format."""
    return {
        "userEnteredFormat": {
            "numberFormat": {"type": "NUMBER", "pattern": pattern}
        }
    }


# ---------------------------------------------------------------------------
# Monthly worksheet helpers
# ---------------------------------------------------------------------------


def _get_or_create_monthly_sheet(year_month: str) -> gspread.Worksheet:
    """Return the worksheet for *year_month* (e.g. ``"2026-03"``).

    If the sheet doesn't exist yet it is created with headers, formulas,
    formatting, validation, and charts.
    """
    ss = _get_spreadsheet()
    try:
        return ss.worksheet(year_month)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=year_month, rows=500, cols=16)
        _setup_headers_and_formulas(ws, year_month)
        logger.info("Created new monthly sheet: %s", year_month)
        return ws


def _setup_headers_and_formulas(ws: gspread.Worksheet, year_month: str) -> None:
    """Set up a new monthly sheet: headers, formulas, running balance,
    number formatting, category/type dropdowns, and embedded charts."""

    prev = _previous_month(year_month)

    # --- 1. Cell data ---------------------------------------------------

    # Data headers (A1:E1)
    ws.update("A1:E1", [_HEADERS], value_input_option="USER_ENTERED")

    # Summary block (G:H)
    #   Row 1  Metric / Value  (header)
    #   Row 2  Total Income
    #   Row 3  Total Expenses
    #   Row 4  Net Savings
    #   Row 5  (blank)
    #   Row 6  Carried Forward  ← from previous month's Running Total
    #   Row 7  Running Total    ← Carried Forward + this month's Net
    #   Row 8  (blank)
    #   Row 9  Category Breakdown (header)
    #   Row 10+ per-category SUMIF
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

    cat_start_0 = len(summary_cells)  # 0-indexed row where categories begin
    for cat in _FORMULA_CATEGORIES:
        summary_cells.append([cat, f'=SUMIF(C:C,"{cat}",D:D)'])
    cat_end_0 = len(summary_cells)

    ws.update(
        f"G1:H{cat_end_0}",
        summary_cells,
        value_input_option="USER_ENTERED",
    )

    # --- 2. Formatting, validation & charts (single batch call) ---------

    sid = ws.id

    requests: list[dict] = [
        # Bold labels
        _fmt_bold(sid, 0, 1, 0, 5),      # A1:E1 data headers
        _fmt_bold(sid, 0, 1, 6, 8),      # G1:H1 summary header
        _fmt_bold(sid, 5, 7, 6, 7),      # G6:G7 (Carried Forward, Running Total)
        _fmt_bold(sid, 8, 9, 6, 7),      # G9 (Category Breakdown)

        # Number format: Amount column D (#,##0.00)
        {
            "repeatCell": {
                "range": _grid_range(sid, 1, 500, 3, 4),
                "cell": _num_fmt("#,##0.00"),
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        # Number format: Summary values column H
        {
            "repeatCell": {
                "range": _grid_range(sid, 1, cat_end_0, 7, 8),
                "cell": _num_fmt("#,##0.00"),
                "fields": "userEnteredFormat.numberFormat",
            }
        },

        # Dropdown: Category (column C) — non-strict, allows custom values
        {
            "setDataValidation": {
                "range": _grid_range(sid, 1, 500, 2, 3),
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": c} for c in _FORMULA_CATEGORIES],
                    },
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        },
        # Dropdown: Type (column E) — strict Income/Expense only
        {
            "setDataValidation": {
                "range": _grid_range(sid, 1, 500, 4, 5),
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": "Income"},
                            {"userEnteredValue": "Expense"},
                        ],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        },

        # ---- Charts ----

        # Pie chart — category breakdown
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "By Category",
                        "pieChart": {
                            "legendPosition": "RIGHT_LEGEND",
                            "domain": {
                                "sourceRange": {
                                    "sources": [_grid_range(sid, cat_start_0, cat_end_0, 6, 7)]
                                }
                            },
                            "series": {
                                "sourceRange": {
                                    "sources": [_grid_range(sid, cat_start_0, cat_end_0, 7, 8)]
                                }
                            },
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": sid, "rowIndex": 0, "columnIndex": 9},
                            "widthPixels": 500,
                            "heightPixels": 300,
                        }
                    },
                }
            }
        },

        # Column chart — Income vs Expenses
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Income vs Expenses",
                        "basicChart": {
                            "chartType": "COLUMN",
                            "legendPosition": "NO_LEGEND",
                            "domains": [
                                {
                                    "domain": {
                                        "sourceRange": {
                                            "sources": [_grid_range(sid, 1, 3, 6, 7)]
                                        }
                                    }
                                }
                            ],
                            "series": [
                                {
                                    "series": {
                                        "sourceRange": {
                                            "sources": [_grid_range(sid, 1, 3, 7, 8)]
                                        }
                                    }
                                }
                            ],
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": sid, "rowIndex": 16, "columnIndex": 9},
                            "widthPixels": 500,
                            "heightPixels": 300,
                        }
                    },
                }
            }
        },
    ]

    _get_spreadsheet().batch_update({"requests": requests})


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
    carried_forward: float = 0.0
    running_total: float = 0.0
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

    # Read running balance from formula cells (use FORMATTED_VALUE to get
    # the evaluated result rather than the raw formula text).
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
    """Return a sorted list of existing monthly worksheet titles (e.g. ``["2026-01", "2026-03"]``)."""
    ss = _get_spreadsheet()
    names: list[str] = []
    for ws in ss.worksheets():
        # Only include sheets that look like YYYY-MM
        title = ws.title
        if len(title) == 7 and title[4] == "-" and title[:4].isdigit() and title[5:].isdigit():
            names.append(title)
    return sorted(names)
