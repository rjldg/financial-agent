"""Telegram bot entry-point — handles /start and natural-language messages."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import ALLOWED_USER_ID, TELEGRAM_TOKEN
from app.llm_parser import RateLimitError, parse_transaction
from app.sheets_db import append_transaction, get_monthly_summary, list_monthly_sheets

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_authorised(update: Update) -> bool:
    """Return True only when the message comes from the allowed user."""
    return update.effective_user is not None and update.effective_user.id == ALLOWED_USER_ID


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command — send welcome text."""
    if not _is_authorised(update):
        return

    await update.message.reply_text(
        "👋 Hi! I'm your personal finance tracker.\n\n"
        "Just send me a message like:\n"
        '  • "Spent 150 on lunch at McDo"\n'
        '  • "Got my 600k salary"\n'
        '  • "Paid 500 for electricity bill"\n\n'
        "I'll log it to your Google Sheet automatically.\n\n"
        "Commands:\n"
        "  /summary — this month's financial report\n"
        "  /summary 2026-03 — report for a specific month\n"
        "  /months — list all tracked months"
    )


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/summary [YYYY-MM] — show financial report for a month."""
    if not _is_authorised(update):
        return

    # Determine which month to report on
    if context.args:
        year_month = context.args[0]
    else:
        year_month = datetime.now(tz=timezone.utc).strftime("%Y-%m")

    try:
        s = get_monthly_summary(year_month)
    except Exception:
        logger.exception("Failed to fetch summary for %s", year_month)
        await update.message.reply_text(
            f"❌ No data found for {year_month}. "
            "Use /months to see available months."
        )
        return

    # Build the report
    lines = [
        f"📊 *{year_month} Financial Summary*",
        "",
        f"💰 Total Income:    {s.total_income:>12,.2f}",
        f"💸 Total Expenses:  {s.total_expenses:>12,.2f}",
        f"💵 Net Savings:     {s.net_savings:>12,.2f}",
        f"📝 Transactions:    {s.transaction_count}",
        "",
        f"📦 Carried Forward: {s.carried_forward:>12,.2f}",
        f"🏦 Running Total:   {s.running_total:>12,.2f}",
    ]

    if s.category_totals:
        lines.append("")
        lines.append("📋 *Breakdown by Category:*")
        for cat, total in s.category_totals.items():
            lines.append(f"  {cat:<16s} {total:>10,.2f}")

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )


async def months_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/months — list all tracked monthly sheets."""
    if not _is_authorised(update):
        return

    try:
        months = list_monthly_sheets()
    except Exception:
        logger.exception("Failed to list monthly sheets")
        await update.message.reply_text("❌ Could not retrieve month list.")
        return

    if not months:
        await update.message.reply_text("No monthly sheets found yet. Start logging transactions!")
        return

    listing = "\n".join(f"  • {m}" for m in months)
    await update.message.reply_text(
        f"📅 *Tracked Months:*\n{listing}\n\n"
        "Use /summary YYYY-MM to view a specific month.",
        parse_mode="Markdown",
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any non-command text message."""
    if not _is_authorised(update):
        return

    text = update.message.text
    logger.info("Received message from %s: %s", update.effective_user.id, text)

    try:
        txn = await parse_transaction(text)
    except RateLimitError:
        logger.warning("Rate limit exhausted for message: %s", text)
        await update.message.reply_text(
            "⏳ The AI service is rate-limited right now. "
            "Please wait a minute and try again."
        )
        return
    except Exception:
        logger.exception("LLM parsing failed for message: %s", text)
        await update.message.reply_text(
            "❌ Sorry, I couldn't understand that message. "
            "Try rephrasing it (e.g. 'Spent 200 on groceries')."
        )
        return

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

    try:
        append_transaction(
            date=now,
            description=txn.description,
            category=txn.category,
            amount=txn.amount,
            txn_type=txn.type,
        )
    except Exception:
        logger.exception("Google Sheets append failed")
        await update.message.reply_text(
            "❌ I understood the transaction but failed to write it to Google Sheets. "
            "Please try again in a moment."
        )
        return

    await update.message.reply_text(
        f"✅ Logged: {txn.amount:,.2f} ({txn.category}) — {txn.description}"
    )


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------


def main() -> None:
    """Build and start the Telegram bot (long-polling)."""
    # Python 3.14 removed auto-creation of event loops in get_event_loop(),
    # which python-telegram-bot's run_polling() relies on internally.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("months", months_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot started — listening for messages …")
    app.run_polling()


if __name__ == "__main__":
    main()
