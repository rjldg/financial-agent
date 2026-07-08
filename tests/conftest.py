"""Shared pytest fixtures/config. Sets dummy env vars so importing app.config
(which reads required vars at import time) never raises during tests."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_ID", "123456789")
os.environ.setdefault("SHEET_ID", "test-sheet-id")
os.environ.setdefault("APP_TIMEZONE", "Asia/Manila")
os.environ.setdefault("CURRENCY_SYMBOL", "₱")
