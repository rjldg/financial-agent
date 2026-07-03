from datetime import date

from app.sheets.subscriptions import _row_to_sub, _sub_fields_to_row
from app.models import Subscription


def test_row_to_sub_parses_types():
    row = ["Netflix", "549", "Entertainment", "Expense", "Monthly",
           "1", "", "2026-03-01", "TRUE", "hd plan"]
    s = _row_to_sub(row, row_index=2)
    assert isinstance(s, Subscription)
    assert s.amount == 549.0 and s.day == 1 and s.month is None
    assert s.last_charged == date(2026, 3, 1) and s.active is True and s.row == 2


def test_row_to_sub_inactive_and_yearly():
    row = ["iCloud", "1490", "Utilities", "Expense", "Yearly",
           "15", "6", "", "FALSE", ""]
    s = _row_to_sub(row, row_index=5)
    assert s.active is False and s.month == 6 and s.last_charged is None


def test_sub_fields_to_row_roundtrips():
    fields = {"name": "Spotify", "amount": 149.0, "category": "Entertainment",
              "type": "Expense", "frequency": "Monthly", "day": 5, "month": None}
    row = _sub_fields_to_row(fields, last_charged=date(2026, 3, 5))
    assert row[0] == "Spotify" and row[5] == 5 and row[6] == ""
    assert row[7] == "2026-03-05" and row[8] == "TRUE"
