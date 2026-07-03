"""Transaction logging handler for free-text messages."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import now_local
from app.llm_parser import RateLimitError, parse_transaction
from app.sheets import append_transaction
from app.bot.handlers.reports import is_authorised

logger = logging.getLogger(__name__)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    text = update.message.text
    logger.info("Received message from %s: %s", update.effective_user.id, text)
    try:
        txn = await parse_transaction(text)
    except RateLimitError:
        await update.message.reply_text(
            "⏳ The AI service is rate-limited right now. Please wait a minute and try again."
        )
        return
    except Exception:
        logger.exception("LLM parsing failed for message: %s", text)
        await update.message.reply_text(
            "❌ Sorry, I couldn't understand that message. "
            "Try rephrasing it (e.g. 'Spent 200 on groceries')."
        )
        return
    now = now_local().strftime("%Y-%m-%d %H:%M")
    try:
        append_transaction(date=now, description=txn.description, category=txn.category,
                           amount=txn.amount, txn_type=txn.type)
    except Exception:
        logger.exception("Google Sheets append failed")
        await update.message.reply_text(
            "❌ I understood the transaction but failed to write it to Google Sheets."
        )
        return
    reply = f"✅ Logged: {txn.amount:,.2f} ({txn.category}) — {txn.description}"
    if txn.type == "Expense":
        try:
            from app.sheets.budgets import budget_alert_for
            alert = budget_alert_for(txn.category, now[:7])
            if alert:
                reply += f"\n{alert}"
        except Exception:
            logger.exception("Budget alert lookup failed (non-fatal)")
    await update.message.reply_text(reply)
