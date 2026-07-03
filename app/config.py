"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID: int = int(os.environ["ALLOWED_USER_ID"])

# --- Local LLM (Ollama) ---
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3:4b")

# --- Google Sheets ---
GOOGLE_SHEETS_CREDENTIALS_FILE: str = os.environ.get(
    "GOOGLE_SHEETS_CREDENTIALS_FILE", "service_account.json"
)
SHEET_ID: str = os.environ["SHEET_ID"]
# --- Localization ---
from datetime import datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE: str = os.environ.get("APP_TIMEZONE", "Asia/Manila")
TZ = ZoneInfo(APP_TIMEZONE)


def now_local() -> datetime:
    """Current time in the configured application timezone."""
    return datetime.now(tz=TZ)


CURRENCY_CODE: str = os.environ.get("CURRENCY_CODE", "PHP")
CURRENCY_SYMBOL: str = os.environ.get("CURRENCY_SYMBOL", "₱")

# --- Scheduling ---
WEEKLY_DIGEST_DAY: str = os.environ.get("WEEKLY_DIGEST_DAY", "mon")  # mon..sun
WEEKLY_DIGEST_HOUR: int = int(os.environ.get("WEEKLY_DIGEST_HOUR", "8"))
SUB_CHECK_HOUR: int = int(os.environ.get("SUB_CHECK_HOUR", "8"))

# --- Budgets ---
BUDGET_ALERT_THRESHOLD: float = float(os.environ.get("BUDGET_ALERT_THRESHOLD", "0.8"))


def validate_config() -> list[str]:
    """Return human-readable configuration problems (empty list means OK)."""
    problems: list[str] = []
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "your-telegram-bot-token":
        problems.append("TELEGRAM_TOKEN is not set.")
    if not SHEET_ID or SHEET_ID == "your-google-sheet-id":
        problems.append("SHEET_ID is not set.")
    if not os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
        problems.append(f"Google credentials file not found: {GOOGLE_SHEETS_CREDENTIALS_FILE}")
    try:
        ZoneInfo(APP_TIMEZONE)
    except Exception:
        problems.append(f"Invalid APP_TIMEZONE: {APP_TIMEZONE}")
    return problems
