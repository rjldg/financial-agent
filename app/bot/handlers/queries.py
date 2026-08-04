"""Query commands: /search, /insights, /ask."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import now_local
from app.formatting import format_money
from app.insights import compose_insights, compose_query_answer
from app.llm_parser import RateLimitError, RouterParseError, route_message
from app.sheets.transactions import get_monthly_summary, list_monthly_sheets, search_transactions
from app.bot.handlers.reports import is_authorised
from app.bot.handlers.transactions import _UNREADABLE_REPLY

logger = logging.getLogger(__name__)

# Same wording message_handler uses for the same failure - /ask should not
# feel like a different, less-finished feature just because it's a command.
_RATE_LIMITED_REPLY = (
    "⏳ The AI service is rate-limited right now. Please wait a minute and try again."
)


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /search <term>")
        return
    term = " ".join(context.args)
    try:
        rows = search_transactions(term)
    except Exception:
        logger.exception("Search failed")
        await update.message.reply_text("❌ Search failed.")
        return
    if not rows:
        await update.message.reply_text(f"No matches for '{term}'.")
        return
    lines = [f"🔎 *Results for '{term}':*"]
    for ym, date, desc, cat, amount, ttype in rows:
        try:
            amt = format_money(float(amount))
        except (ValueError, TypeError):
            amt = str(amount)
        lines.append(f"  • {date} — {desc} ({cat}) {amt}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def _previous_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


async def insights_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    ym = now_local().strftime("%Y-%m")
    try:
        current = get_monthly_summary(ym)
    except Exception:
        await update.message.reply_text(f"❌ No data for {ym} yet.")
        return
    previous = None
    try:
        previous = get_monthly_summary(_previous_month(ym))
    except Exception:
        pass
    await update.message.reply_text(compose_insights(current, previous), parse_mode="Markdown")


async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ask <question about your finances>")
        return
    try:
        result = await route_message(" ".join(context.args))
    except RateLimitError:
        await update.message.reply_text(_RATE_LIMITED_REPLY)
        return
    except RouterParseError:
        logger.exception("Router returned an unusable answer for /ask: %s", context.args)
        await update.message.reply_text(_UNREADABLE_REPLY)
        return
    if result.intent == "query" and result.query:
        period = result.query.period or now_local().strftime("%Y-%m")
        try:
            s = get_monthly_summary(period)
        except Exception:
            await update.message.reply_text(f"❌ No data for {period}.")
            return
        await update.message.reply_text(
            compose_query_answer(s, result.query.metric, result.query.category, period)
        )
    else:
        await update.message.reply_text("I couldn't turn that into a finance question.")
