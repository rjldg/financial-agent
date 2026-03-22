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