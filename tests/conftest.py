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
