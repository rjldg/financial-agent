# 💰 Chat-to-Sheet — Personal Finance Tracker Bot

A **Telegram bot** that turns natural-language messages about your spending and income into structured data in **Google Sheets** — powered by a **local Ollama LLM** running entirely on your machine.

Send a message like _"Spent 150 on lunch at McDo"_ and the bot will extract the amount, category, and description, then log it to a monthly Google Sheet tab complete with live formulas, charts, and running balances.

---

## ✨ Features

- **Natural Language Input** — Text the bot naturally to log one or more transactions in a single message.
- **Local AI-Powered Extraction** — A locally hosted Ollama model extracts `amount`, `category`, `description`, and `type` (Income/Expense) with guaranteed structured output via Pydantic.
- **100% Private & Free** — The LLM runs on your own hardware. No API keys, no cloud AI costs, no data sent to third parties.
- **Recurring Subscriptions** — Track monthly/yearly subscriptions, pause or resume them, and auto-log due charges.
- **📊 Dashboard Tab** — Rebuild a Sheet dashboard with KPI cards, trend chart, top categories, upcoming subscriptions, and budget status.
- **Budgets & Alerts** — Set monthly category budgets and receive warnings as spending approaches the configured threshold.
- **Natural-Language Queries** — Ask finance questions with `/ask`, get spending insights with `/insights`, and find transactions with `/search`.
- **Inline Quick-Fix Buttons** — Correct transaction category, type, or amount from Telegram without editing the sheet manually.
- **Receipt OCR** — Send a receipt photo and log the extracted transaction.
- **Weekly Digest** — Receive scheduled weekly summaries of spend and upcoming subscription charges.
- **Currency & Timezone Support** — Configure display currency and local scheduling via environment variables.
- **Auto-Monthly Sheets** — A new tab (e.g. `2026-03`) is created automatically each month.
- **Live Formulas, Charts, and Running Balance** — Monthly tabs include totals, category breakdowns, charts, and a carried-forward running total.
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
 2026-03-21     McDo lunch    Food        150.00    Expense    │  Total Income       600,000.00
 2026-03-21     Salary        Salary     600,000.00   Income     │  Total Expenses     2,350.00
                                                               │  Net Savings        597,650.00
                                                               │
                                                               │  Carried Forward        0.00
                                                               │  Running Total      597,650.00
                                                               │
                                                               │  Category Breakdown
                                                               │  Food                150.00
                                                               │  Salary             600,000.00
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

Ollama will start automatically on `http://127.0.0.1:11434`. You can verify it's running:

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

# Ollama (optional — 127.0.0.1 is recommended to avoid IPv6 DNS timeout delays on Windows)
OLLAMA_BASE_URL=http://127.0.0.1:11434
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

## ⬆️ Upgrading an Existing Deployment

If you're updating a bot that's already running against a live Google Sheet (e.g. as an `nssm` Windows service), follow these steps:

1. **Pull the new code** into your existing checkout.
2. **Reinstall dependencies** in the *exact* environment your service runs from:
   ```bash
   pip install -r requirements.txt
   ```
   This is required — the timezone support needs the **`tzdata`** package (Windows has no built-in tz database), and scheduled jobs need the **`job-queue`** extra. If `tzdata` is missing the bot now falls back to UTC with a warning instead of crashing, but you should still install it. If the `job-queue` extra is missing, recurring subscriptions and the weekly digest are skipped (the bot logs a warning and keeps running).
3. **Review new environment variables** (all optional, sensible defaults) in the **Environment Variables Reference** section below — e.g. `APP_TIMEZONE`, `CURRENCY_SYMBOL`, `OLLAMA_KEEP_ALIVE`, `ENABLE_RECEIPT_OCR`. Add any you want to override to your `.env`.
4. **Restart the bot / service.** On first start it creates the `📊 Dashboard`, `⚙ Subscriptions`, `🎯 Budgets`, and a hidden `_MonthlyIndex` tab if missing, and pins the Dashboard to the front — this changes your tab order but never touches transaction data.
5. **Restyle older monthly tabs** (optional): run **`/retheme`** in Telegram to apply the new Bold Finance theme to month tabs created before this version. New tabs are themed automatically. `/retheme` only changes formatting and is safe to re-run.
6. **Refresh the dashboard** (optional): run **`/rebuild`** to populate the `📊 Dashboard` from your existing history.

> **Tip:** Your existing transaction data is never rewritten or deleted by the upgrade. To be extra safe, you can first point `SHEET_ID` at a **copy** of your sheet, verify the bot starts and behaves as expected, then switch back to the real sheet.

> **Behavior changes to expect:** dates are now recorded in `APP_TIMEZONE` (default `Asia/Manila`) instead of UTC, and each text message makes an extra "router" LLM call to classify log-vs-question and support multi-item logging.

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome + quick guide |
| `/help` | List every command |
| `/summary [YYYY-MM]` | Monthly report |
| `/months` | List tracked months |
| `/insights` | Top spend + month-over-month |
| `/ask <question>` | Natural-language finance question |
| `/search <term>` | Find transactions by keyword |
| `/addsub <name> <amount> <category> <monthly\|yearly> day=<d> [month=<m>]` | Add a subscription |
| `/subs` | List subscriptions |
| `/rmsub <name>` | Remove a subscription |
| `/togglesub <name>` | Pause/resume a subscription |
| `/setbudget <category> <amount>` | Set a monthly category budget |
| `/budgets` | Show budgets vs. spend |
| `/undo` | Remove your last entry |
| `/rebuild` | Rebuild the 📊 Dashboard tab |
| `/retheme` | Restyle existing monthly tabs with the Bold Finance theme |
| _(any text)_ | Log one or more transactions, or ask a question |
| _(photo)_ | Log a transaction from a receipt image |

## 🔁 Subscriptions

Subscriptions live in a dedicated `Subscriptions` tab and can be managed from Telegram with `/addsub`, `/subs`, `/rmsub`, and `/togglesub`. The scheduler checks due monthly or yearly charges in the configured timezone and auto-logs each subscription only once per billing period.

**A monthly subscription is charged at most once per calendar month.** The
`LastCharged` cell records the month that has been settled, not merely the last
date anything happened, so the next charge always falls in a later month. That
is what stops a second charge appearing when you move a subscription's
`DayOfMonth` later mid-cycle.

Two consequences if you edit the tab by hand:

- Setting `DayOfMonth` to `31` means the true end of each month — 31, 30, or 28/29
  as appropriate — not "skip short months".
- Editing `LastCharged` to a date inside a month that was never charged will skip
  that month. To make a month chargeable again, set `LastCharged` to a date in the
  **previous** month.

## 📊 Dashboard

The `📊 Dashboard` tab summarizes your finances across monthly tabs. Use `/rebuild` to refresh KPI cards, trend chart, top categories, upcoming subscriptions, and budget status after manual sheet edits or when you want a clean dashboard rebuild.

The Bold Finance theme (dark headers, banded rows, color-coded category tags, currency formatting) is applied automatically to **newly created** monthly tabs. To restyle **existing** monthly tabs that predate the theme, run `/retheme` — it applies the styling in place without touching your data.

## 🎯 Budgets

Budgets live in a dedicated `Budgets` tab and are configured with `/setbudget <category> <amount>`. When a new expense pushes a category past `BUDGET_ALERT_THRESHOLD`, the bot includes an alert so you can adjust spending before the month ends.

### Example `/summary` Output

```
📊 2026-03 Financial Summary

💰 Total Income:        600,000.00
💸 Total Expenses:      2,350.00
💵 Net Savings:         597,650.00
📝 Transactions:       8

📦 Carried Forward:         0.00
🏦 Running Total:       597,650.00

📋 Breakdown by Category:
  Salary               600,000.00
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
| `OLLAMA_BASE_URL` | No | `http://127.0.0.1:11434` | Base URL of the local Ollama server (use `127.0.0.1` to bypass IPv6 DNS resolution issues on Windows) |
| `OLLAMA_MODEL` | No | `gemma3:4b` | Ollama model to use for extraction |
| `OLLAMA_VISION_MODEL` | No | same as `OLLAMA_MODEL` | Ollama model to use for receipt photos. Leave unset if your text model already reads images (e.g. `gemma3:4b`) — then one model serves both and never needs swapping. Only set this if you want a *different* model for receipts. |
| `OLLAMA_NUM_CTX` | No | `2048` | Context window (tokens) given to Ollama. `2048` comfortably fits the router prompt (~600 tokens) |
| `OLLAMA_KEEP_ALIVE` | No | `30m` | How long Ollama keeps the model loaded in VRAM after a reply. The default holds ~2.9 GB of VRAM for 30 minutes after each message, trading memory for faster replies to the next message — this is intended |
| `APP_TIMEZONE` | No | `Asia/Manila` | IANA timezone for local dates and scheduled jobs |
| `CURRENCY_CODE` | No | `PHP` | ISO-like currency code used for labels |
| `CURRENCY_SYMBOL` | No | `₱` | Currency symbol shown in bot replies and sheets |
| `WEEKLY_DIGEST_DAY` | No | `mon` | Day of week for the weekly digest (`mon`..`sun`) |
| `WEEKLY_DIGEST_HOUR` | No | `8` | Local hour for the weekly digest |
| `SUB_CHECK_HOUR` | No | `8` | Local hour for recurring subscription checks |
| `BUDGET_ALERT_THRESHOLD` | No | `0.8` | Fraction of budget spend that triggers alerts |
| `ENABLE_RECEIPT_OCR` | No | `true` | When `false`, disable the receipt-photo (OCR) handler |

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
