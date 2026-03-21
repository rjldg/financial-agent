"""Application configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]

# Hardcoded owner user ID — replace with your own Telegram numeric user ID.
# You can find it by messaging @userinfobot on Telegram.
ALLOWED_USER_ID: int = int(os.environ["ALLOWED_USER_ID"])  # TODO: set your Telegram user ID here

# --- Google Gemini ---
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# --- Google Sheets ---
GOOGLE_SHEETS_CREDENTIALS_FILE: str = os.environ.get(
    "GOOGLE_SHEETS_CREDENTIALS_FILE", "service_account.json"
)
SHEET_ID: str = os.environ["SHEET_ID"]
