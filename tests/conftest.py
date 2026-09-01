"""Shared pytest fixtures/config. Sets dummy env vars so importing app.config
(which reads required vars at import time) never raises during tests."""
import json
import os

import pytest
from gspread.exceptions import APIError
from requests import Response

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_ID", "123456789")
os.environ.setdefault("SHEET_ID", "test-sheet-id")
os.environ.setdefault("APP_TIMEZONE", "Asia/Manila")
os.environ.setdefault("CURRENCY_SYMBOL", "₱")


@pytest.fixture
def api_error():
    """Build a real gspread APIError carrying a given HTTP status code."""
    def _make(code: int, message: str = "boom") -> APIError:
        resp = Response()
        resp.status_code = code
        resp._content = json.dumps(
            {"error": {"code": code, "message": message, "status": "ERROR"}}
        ).encode()
        return APIError(resp)
    return _make


class FakeWorksheet:
    """Minimal stand-in for a gspread worksheet."""

    id = 1

    def update(self, *args, **kwargs):
        pass


class FakeSpreadsheet:
    """Stand-in for the real sheet.

    `errors` maps a tab title to the exception its lookup raises; every other
    title resolves to a worksheet that already exists. Tabs this is asked to
    create are recorded in `added`.
    """

    def __init__(self, errors: dict):
        self.errors = errors
        self.added: list[str] = []

    def worksheet(self, title):
        if title in self.errors:
            raise self.errors[title]
        return FakeWorksheet()

    def add_worksheet(self, title, rows, cols):
        self.added.append(title)
        return FakeWorksheet()
