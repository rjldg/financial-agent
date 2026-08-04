"""Application configuration loaded from environment variables."""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- Telegram ---
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID: int = int(os.environ["ALLOWED_USER_ID"])

# --- Local LLM (Ollama) ---
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
# gemma3:4b reads images too, so by default one model serves text and receipts
# and no swap ever happens. Point this elsewhere only if the text model changes.
OLLAMA_VISION_MODEL: str = os.environ.get("OLLAMA_VISION_MODEL", OLLAMA_MODEL)
# 2048 fits the prompt (~600 tokens) and measured 2.68 GB on a 6 GB card.
OLLAMA_NUM_CTX: int = int(os.environ.get("OLLAMA_NUM_CTX", "2048"))
OLLAMA_KEEP_ALIVE: str = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

# --- Google Sheets ---
GOOGLE_SHEETS_CREDENTIALS_FILE: str = os.environ.get(
    "GOOGLE_SHEETS_CREDENTIALS_FILE", "service_account.json"
)
SHEET_ID: str = os.environ["SHEET_ID"]
# --- Localization ---
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

APP_TIMEZONE: str = os.environ.get("APP_TIMEZONE", "Asia/Manila")
try:
    TZ = ZoneInfo(APP_TIMEZONE)
except Exception:  # e.g. ZoneInfoNotFoundError when 'tzdata' is missing on Windows
    logger.warning(
        "Timezone %r is unavailable (is the 'tzdata' package installed? "
        "run: pip install -r requirements.txt). Falling back to UTC.",
        APP_TIMEZONE,
    )
    TZ = timezone.utc


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


# --- Feature toggles ---
def _flag(name: str, default: bool) -> bool:
    """Parse a boolean env var. Falsy values: 0/false/no/off (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


# When False, the receipt-photo handler is not registered at all.
ENABLE_RECEIPT_OCR: bool = _flag("ENABLE_RECEIPT_OCR", True)


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
        problems.append(
            f"Timezone {APP_TIMEZONE!r} unavailable — install 'tzdata' "
            "(pip install -r requirements.txt); using UTC as a fallback."
        )
    return problems
