"""Google Sheets client singleton and low-level request helpers."""
from __future__ import annotations

import logging
import time

import gspread
from gspread.exceptions import APIError

from app.config import CURRENCY_SYMBOL, GOOGLE_SHEETS_CREDENTIALS_FILE, SHEET_ID

logger = logging.getLogger(__name__)

# Google answers with these when it is briefly overloaded or throttling us. Any
# other code (revoked key, missing sheet) will fail again just as fast, so
# retrying it only delays the real error.
_TRANSIENT_CODES = {429, 500, 502, 503}
_RETRY_ATTEMPTS = 3


def retry_transient(fn, *args, **kwargs):
    """Run a Sheets call, riding out Google's momentary failures.

    Without this a single 503 during the daily run makes a subscription miss
    its due date with nothing posted and no warning.
    """
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except APIError as exc:
            if exc.code not in _TRANSIENT_CODES or attempt == _RETRY_ATTEMPTS - 1:
                raise
            delay = 2 ** attempt
            logger.warning("Sheets call failed (%s); retrying in %ss", exc.code, delay)
            time.sleep(delay)

# Sheets number-format pattern for monetary cells, honoring the configured symbol.
MONEY_PATTERN = f'"{CURRENCY_SYMBOL}"#,##0.00'

_spreadsheet: gspread.Spreadsheet | None = None


def get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet
    if _spreadsheet is None:
        gc = gspread.service_account(filename=GOOGLE_SHEETS_CREDENTIALS_FILE)
        _spreadsheet = gc.open_by_key(SHEET_ID)
        logger.info("Connected to Google Sheet: %s", _spreadsheet.title)
    return _spreadsheet


def invalidate() -> None:
    """Reset cached handle so the next call re-authenticates."""
    global _spreadsheet
    _spreadsheet = None


def batch_update(requests: list[dict]) -> None:
    """Send a batchUpdate with the given requests."""
    get_spreadsheet().batch_update({"requests": requests})


def grid_range(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """Sheets API GridRange dict (0-indexed, exclusive end)."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": r0,
        "endRowIndex": r1,
        "startColumnIndex": c0,
        "endColumnIndex": c1,
    }


def num_fmt(pattern: str) -> dict:
    """CellData dict carrying a number format."""
    return {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}}


def fmt_bold(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """repeatCell request that bolds a range."""
    return {
        "repeatCell": {
            "range": grid_range(sheet_id, r0, r1, c0, c1),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }
    }
