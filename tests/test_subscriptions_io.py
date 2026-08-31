from datetime import date

import pytest

from app.sheets import subscriptions
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


class _FakeWorksheet:
    def update(self, *args, **kwargs):
        pass


class _FakeSpreadsheet:
    """Stands in for the real sheet, recording any tab it is asked to create."""

    def __init__(self, lookup_error):
        self.lookup_error = lookup_error
        self.added: list[str] = []

    def worksheet(self, title):
        raise self.lookup_error

    def add_worksheet(self, title, rows, cols):
        self.added.append(title)
        return _FakeWorksheet()


def test_ensure_subs_tab_creates_the_tab_when_it_is_genuinely_missing(monkeypatch):
    from gspread.exceptions import WorksheetNotFound

    ss = _FakeSpreadsheet(WorksheetNotFound("nope"))
    monkeypatch.setattr(subscriptions, "get_spreadsheet", lambda: ss)

    subscriptions.ensure_subs_tab()

    assert ss.added == [subscriptions.SUBS_SHEET]


def test_ensure_subs_tab_propagates_api_errors_instead_of_creating(monkeypatch, api_error):
    """A Google outage is not 'the tab is missing'.

    Creating a second Subscriptions tab would leave the bot reading an empty
    one and silently believing there are no subscriptions at all.
    """
    ss = _FakeSpreadsheet(api_error(503))
    monkeypatch.setattr(subscriptions, "get_spreadsheet", lambda: ss)

    with pytest.raises(Exception) as excinfo:
        subscriptions.ensure_subs_tab()

    assert excinfo.value.code == 503
    assert ss.added == []
