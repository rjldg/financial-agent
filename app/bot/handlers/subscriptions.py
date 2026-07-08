"""Subscription management commands: /addsub /subs /rmsub /togglesub."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import now_local
from app.formatting import format_money
from app.models import CATEGORIES
from app.sheets import subscriptions as subs
from app.bot.handlers.reports import is_authorised

logger = logging.getLogger(__name__)


async def addsub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    try:
        fields = subs.parse_addsub_args(context.args)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    if fields["category"] not in CATEGORIES:
        await update.message.reply_text(
            f"❌ Unknown category '{fields['category']}'. Allowed: {', '.join(CATEGORIES)}"
        )
        return
    # New subs set LastCharged = today so prior periods are not back-charged.
    subs.add_subscription(fields, last_charged=now_local().date())
    freq = fields["frequency"].lower()
    when = f"day {fields['day']}" + (f" of month {fields['month']}" if fields["month"] else "")
    await update.message.reply_text(
        f"✅ Added subscription *{fields['name']}* — {format_money(fields['amount'])} "
        f"({fields['category']}), {freq} on {when}.",
        parse_mode="Markdown",
    )


async def subs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    items = subs.list_subscriptions()
    if not items:
        await update.message.reply_text("No subscriptions yet. Add one with /addsub.")
        return
    today = now_local().date()
    lines = ["⚙ *Subscriptions:*"]
    for s in items:
        base = s.last_charged or today
        nxt = subs.next_due_date(base, s.frequency, s.day, s.month)
        status = "" if s.active else " (paused)"
        lines.append(f"  • {s.name}{status} — {format_money(s.amount)} · next {nxt.isoformat()}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def rmsub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /rmsub <name>")
        return
    ok = subs.remove_subscription(context.args[0])
    await update.message.reply_text(
        f"🗑 Removed {context.args[0]}." if ok else f"❌ No subscription named {context.args[0]}."
    )


async def togglesub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /togglesub <name>")
        return
    state = subs.toggle_subscription(context.args[0])
    if state is None:
        await update.message.reply_text(f"❌ No subscription named {context.args[0]}.")
    else:
        await update.message.reply_text(
            f"{'▶️ Resumed' if state else '⏸ Paused'} {context.args[0]}."
        )
