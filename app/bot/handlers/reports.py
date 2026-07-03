"""Report/informational command handlers: /start, /summary, /months."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import ALLOWED_USER_ID, now_local
from app.sheets import get_monthly_summary, list_monthly_sheets

logger = logging.getLogger(__name__)

COMMANDS: list[tuple[str, str]] = [
    ("start", "Welcome + quick guide"),
    ("help", "List every command"),
    ("summary", "Monthly report (/summary YYYY-MM)"),
    ("months", "List tracked months"),
    ("insights", "Top spend + month-over-month"),
    ("ask", "Ask a finance question"),
    ("search", "Find transactions by keyword"),
    ("addsub", "Add a subscription"),
    ("subs", "List subscriptions"),
    ("rmsub", "Remove a subscription"),
    ("togglesub", "Pause/resume a subscription"),
    ("setbudget", "Set a category budget"),
    ("budgets", "Show budgets vs spend"),
    ("undo", "Remove your last entry"),
    ("rebuild", "Rebuild the dashboard"),
]


def is_authorised(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == ALLOWED_USER_ID


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    await update.message.reply_text(
        "👋 *Personal Finance Tracker*\n\n"
        "Just text me naturally:\n"
        '  • "Spent 150 on lunch and 90 on grab"\n'
        '  • "Got my 48k salary"\n'
        "  • or send a 🧾 *receipt photo*\n\n"
        "Ask me things: _how much did I spend on food this month?_\n\n"
        "Subscriptions auto-log monthly/yearly. Set budgets to get alerts.\n"
        "Type /help for the full command list.",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    lines = ["*Commands:*"] + [f"  /{name} — {desc}" for name, desc in COMMANDS]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    year_month = context.args[0] if context.args else now_local().strftime("%Y-%m")
    try:
        s = get_monthly_summary(year_month)
    except Exception:
        logger.exception("Failed to fetch summary for %s", year_month)
        await update.message.reply_text(
            f"❌ No data found for {year_month}. Use /months to see available months."
        )
        return
    lines = [
        f"📊 *{year_month} Financial Summary*", "",
        f"💰 Total Income:    {s.total_income:>12,.2f}",
        f"💸 Total Expenses:  {s.total_expenses:>12,.2f}",
        f"💵 Net Savings:     {s.net_savings:>12,.2f}",
        f"📝 Transactions:    {s.transaction_count}", "",
        f"📦 Carried Forward: {s.carried_forward:>12,.2f}",
        f"🏦 Running Total:   {s.running_total:>12,.2f}",
    ]
    if s.category_totals:
        lines.append("")
        lines.append("📋 *Breakdown by Category:*")
        for cat, total in s.category_totals.items():
            lines.append(f"  {cat:<16s} {total:>10,.2f}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def months_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
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
        f"📅 *Tracked Months:*\n{listing}\n\nUse /summary YYYY-MM to view a specific month.",
        parse_mode="Markdown",
    )


async def rebuild_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    await update.message.reply_text("🔧 Rebuilding dashboard …")
    try:
        from app.sheets import dashboard
        dashboard.rebuild_dashboard()
    except Exception:
        logger.exception("Dashboard rebuild failed")
        await update.message.reply_text("❌ Rebuild failed. Check the logs.")
        return
    await update.message.reply_text("✅ Dashboard rebuilt.")
