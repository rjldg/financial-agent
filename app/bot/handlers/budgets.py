"""Budget commands: /setbudget /budgets."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import now_local
from app.formatting import format_money
from app.models import CATEGORIES
from app.sheets import budgets
from app.bot.handlers.reports import is_authorised

logger = logging.getLogger(__name__)


async def setbudget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setbudget <category> <amount>")
        return
    category = context.args[0]
    if category not in CATEGORIES:
        await update.message.reply_text(
            f"❌ Unknown category '{category}'. Allowed: {', '.join(CATEGORIES)}"
        )
        return
    try:
        limit = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    budgets.set_budget(category, limit)
    await update.message.reply_text(
        f"🎯 Budget set: {category} = {format_money(limit)} / month."
    )


async def budgets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    limits = budgets.get_budgets()
    if not limits:
        await update.message.reply_text("No budgets set. Use /setbudget <category> <amount>.")
        return
    from app.sheets.transactions import get_monthly_summary
    ym = now_local().strftime("%Y-%m")
    try:
        spent = get_monthly_summary(ym).category_totals
    except Exception:
        spent = {}
    lines = [f"🎯 *Budgets · {ym}:*"]
    for s in budgets.budget_status(spent, limits):
        pct = round(s.ratio * 100)
        flag = " ⚠" if s.ratio >= 1.0 else ""
        lines.append(f"  • {s.category}: {format_money(s.spent)} / {format_money(s.limit)} ({pct}%){flag}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
