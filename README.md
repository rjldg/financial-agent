# 💰 Chat-to-Sheet — Personal Finance Tracker Bot

A **Telegram bot** that turns natural-language messages about your spending and income into structured data in **Google Sheets** — powered by a **local Ollama LLM** running entirely on your machine.

Send a message like _"Spent 150 on lunch at McDo"_ and the bot will extract the amount, category, and description, then log it to a monthly Google Sheet tab complete with live formulas, charts, and running balances.

---

## ✨ Features

- **Natural Language Input** — No forms, no menus. Just text the bot like you'd text a friend.
- **Local AI-Powered Extraction** — A locally hosted Ollama model extracts `amount`, `category`, `description`, and `type` (Income/Expense) with guaranteed structured output via Pydantic.
- **100% Private & Free** — The LLM runs on your own hardware. No API keys, no cloud AI costs, no data sent to third parties.
- **Auto-Monthly Sheets** — A new tab (e.g. `2026-03`) is created automatically each month.
- **Live Formulas** — Total Income, Total Expenses, Net Savings, per-category breakdown — all computed via Google Sheets formulas.
- **Running Balance** — Each month carries forward the previous month's running total, giving you cumulative savings at a glance.
- **Embedded Charts** — Pie chart (by category) and column chart (income vs expenses) are auto-created on each monthly tab.
- **Dropdowns** — Category (13 options) and Type (Income/Expense) columns have data-validation dropdowns for manual edits in the sheet.
- **Number Formatting** — All monetary values formatted as `#,##0.00`.
- **Connection Resilience** — Retries Ollama API calls up to 3× with exponential backoff on connection/timeout errors.
- **Security** — Only responds to a single authorized Telegram user ID; all others are silently ignored.

---

## 📐 Architecture

```
User (Telegram)
  │
  ▼
bot.py ──► llm_parser.py ──► Ollama (local LLM, OpenAI-compatible API)
  │                              │
  │                              ▼
  │                        Transaction (Pydantic model)
  │                              │
  └──► sheets_db.py ─────────────┘──► Google Sheets (gspread)
```

| File | Responsibility |
|---|---|
| `app/config.py` | Loads environment variables, exposes constants |
| `app/llm_parser.py` | Pydantic `Transaction` model + Ollama API call with retry logic |
| `app/sheets_db.py` | Google Sheets auth, monthly tab creation, formulas, charts, append & summary |
| `app/bot.py` | Telegram bot handlers (`/start`, `/summary`, `/months`, message parsing) |

---

## 📊 Google Sheet Layout (Auto-Generated Per Month)

```
  A               B             C           D          E       │   G                     H
───────────────────────────────────────────────────────────────│──────────────────────────────
 Date           Description   Category ▼  Amount     Type ▼   │  Metric               Value
 2026-03-21     McDo lunch    Food        150.00    Expense    │  Total Income     600,000.00
 2026-03-21     Salary        Salary   600,000.00   Income     │  Total Expenses     2,350.00
                                                               │  Net Savings      597,650.00
                                                               │
                                                               │  Carried Forward        0.00
                                                               │  Running Total    597,650.00
                                                               │
                                                               │  Category Breakdown
                                                               │  Food                150.00
                                                               │  Salary          600,000.00
                                                               │  ...

          ┌───────────────────┐    ┌──────────────────────┐
          │  🥧 By Category   │    │  📊 Income vs Expenses│
          │   (Pie Chart)     │    │   (Column Chart)      │
          └───────────────────┘    └──────────────────────┘
```

**Running balance chain:** Each month's "Carried Forward" formula references the previous month's "Running Total" (`=IFERROR('2026-02'!H7, 0)`), so skipped months gracefully return 0.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** (tested on 3.12 and 3.14)
- A **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
- **[Ollama](https://ollama.com/)** installed and running locally
- A **Google Cloud Service Account** with access to Google Sheets API & Drive API
- A **Google Sheet** shared with the service account email as **Editor**

### 1. Install & Start Ollama

Download and install Ollama from [https://ollama.com/download](https://ollama.com/download), then pull the default model:

```bash
ollama pull gemma3:4b
```

Ollama will start automatically on `http://localhost:11434`. You can verify it's running:

```bash
ollama list
```

> You can swap `gemma3:4b` for any other model (e.g. `llama3.2`, `mistral`, `qwen2.5`) by changing the `OLLAMA_MODEL` env var. Larger models will be more accurate but slower.

### 2. Clone & Install

```bash
git clone https://github.com/your-username/financial-agent.git
cd financial-agent

python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_TOKEN=7123456789:AAH...your-token-here
ALLOWED_USER_ID=123456789
SHEET_ID=1BxiMVs0XRA5nF...your-sheet-id

# Ollama (optional — these are the defaults)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
```

### 4. Set Up Google Cloud (One-Time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create or select a project
2. Enable the **Google Sheets API** and **Google Drive API**
3. Go to **IAM & Admin → Service Accounts** → create a service account
4. Create a JSON key → download and save as `service_account.json` in the project root
5. Open your Google Sheet → click **Share** → add the service account email (found in the JSON as `client_email`) with **Editor** permission

### 5. Get Your Telegram User ID

Message [@userinfobot](https://t.me/userinfobot) on Telegram — it will reply with your numeric user ID. Set it as `ALLOWED_USER_ID` in `.env`.

### 6. Run

```bash
python -m app.bot
```

---

## 🐳 Docker Deployment

```bash
# Build and run
docker compose up --build

# Run in background
docker compose up --build -d

# View logs
docker compose logs -f bot

# Stop
docker compose down
```

> **Note:** When running in Docker, Ollama must be reachable from inside the container. If Ollama is running on the host machine, set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in your `.env` file.

The `docker-compose.yml` mounts `service_account.json` read-only and loads `.env` automatically.

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message with usage instructions |
| `/summary` | Financial report for the **current month** |
| `/summary 2026-03` | Financial report for a **specific month** |
| `/months` | List all months that have recorded transactions |
| _(any text)_ | Parse and log a transaction |

### Example `/summary` Output

```
📊 2026-03 Financial Summary

💰 Total Income:      600,000.00
💸 Total Expenses:      2,350.00
💵 Net Savings:       597,650.00
📝 Transactions:       8

📦 Carried Forward:         0.00
🏦 Running Total:     597,650.00

📋 Breakdown by Category:
  Salary             600,000.00
  Food                 1,200.00
  Transport              500.00
  Bills                  650.00
```

---

## ⚙️ Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `ALLOWED_USER_ID` | Yes | — | Your Telegram numeric user ID |
| `SHEET_ID` | Yes | — | Google Sheet document ID (from the URL) |
| `GOOGLE_SHEETS_CREDENTIALS_FILE` | No | `service_account.json` | Path to the service-account JSON |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Base URL of the local Ollama server |
| `OLLAMA_MODEL` | No | `gemma3:4b` | Ollama model to use for extraction |

---

## 🗂 Project Structure

```
financial-agent/
├── app/
│   ├── __init__.py
│   ├── config.py          # Environment variable loading
│   ├── llm_parser.py      # Pydantic model + Ollama structured output
│   ├── sheets_db.py       # Google Sheets: monthly tabs, formulas, charts
│   └── bot.py             # Telegram bot handlers + entry point
├── .env                   # Your secrets (git-ignored)
├── .env.example           # Template for .env
├── .gitignore
├── service_account.json   # Google Cloud SA key (git-ignored)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🔒 Security

- **Single-user only** — the bot silently ignores messages from any Telegram user ID other than `ALLOWED_USER_ID`.
- **Secrets management** — `.env` and `service_account.json` are git-ignored. In Docker, the service-account key is mounted read-only.
- **No data logging** — message content is only logged at INFO level for debugging; no persistent storage of raw messages.
- **Local AI** — all LLM inference runs on your own machine; your financial messages never leave your network.

---

## 🛡 Error Handling

| Scenario | Behavior |
|---|---|
| LLM can't parse message | Bot replies: _"❌ Sorry, I couldn't understand that message."_ |
| Ollama unreachable / timeout | Retries 3× with exponential backoff (2s → 4s → 8s), then: _"⏳ The AI service is unavailable."_ |
| Google Sheets API failure | Bot replies: _"❌ Failed to write to Google Sheets."_ + cached client is invalidated for automatic re-auth |
| Missing month for `/summary` | Bot replies: _"❌ No data found for YYYY-MM."_ |

---

## 💲 Costs

| Service | Cost |
|---|---|
| **Ollama (Local LLM)** | **Free** — runs entirely on your hardware |
| **Google Sheets API** | Free (60 req/min quota) |
| **Google Drive API** | Free |
| **Telegram Bot API** | Free |

This project has **zero ongoing AI costs**. The only compute cost is your own electricity.

---

## 🖥 Recommended Models

The bot works with any model available in Ollama. Smaller models are faster; larger ones are more accurate at following the strict JSON schema.

| Model | Pull Command | Size | Notes |
|---|---|---|---|
| `gemma3:4b` *(default)* | `ollama pull gemma3:4b` | ~3 GB | Fast, good accuracy |
| `llama3.2:3b` | `ollama pull llama3.2:3b` | ~2 GB | Very fast, lightweight |
| `mistral:7b` | `ollama pull mistral:7b` | ~4.1 GB | Strong instruction following |
| `qwen2.5:7b` | `ollama pull qwen2.5:7b` | ~4.4 GB | Excellent JSON accuracy |

Change the active model by updating `OLLAMA_MODEL` in your `.env` file — no code changes needed.

---

## 📝 Supported Categories

The following categories are recognized by the AI and have dedicated formula rows and dropdown entries in the sheet:

`Food` · `Transport` · `Bills` · `Salary` · `Entertainment` · `Shopping` · `Health` · `Utilities` · `Rent` · `Freelance` · `Dating` · `Other`

Custom categories typed by the AI are still recorded — they just won't have a dedicated formula row (but will appear in the `/summary` breakdown).

---

## 📜 License

MIT
