"""Background jobs: subscription catch-up (startup + daily) and weekly digest."""
from __future__ import annotations

import datetime as dt
import logging

from telegram.ext import Application, ContextTypes

from app.config import ALLOWED_USER_ID, SUB_CHECK_HOUR, TZ, now_local
from app.formatting import format_money

logger = logging.getLogger(__name__)


def filter_recent_expense(records: list[dict], today: dt.date, days: int = 7):
    """Sum expense records within the last `days` (inclusive), plus a by-category map."""
    cutoff = today - dt.timedelta(days=days)
    total = 0.0
    by_cat: dict[str, float] = {}
    for r in records:
        raw = str(r.get("Date", "")).strip()[:10]
        try:
            rd = dt.date.fromisoformat(raw)
        except ValueError:
            continue
        if rd < cutoff or rd > today:
            continue
        if str(r.get("Type", "")).strip() != "Expense":
            continue
        try:
            amt = float(r.get("Amount", 0))
        except (ValueError, TypeError):
            continue
        cat = str(r.get("Category", "Other")).strip() or "Other"
        total += amt
        by_cat[cat] = by_cat.get(cat, 0.0) + amt
    return total, by_cat


def compose_weekly_digest(week_total: float, week_by_cat: dict[str, float],
                          upcoming: list[tuple[str, float, dt.date]], today: dt.date) -> str:
    lines = [f"🗓 *Weekly Digest — {today.isoformat()}*",
             f"Spent last 7 days: {format_money(week_total)}"]
    if week_by_cat:
        top = sorted(week_by_cat.items(), key=lambda kv: -kv[1])[:3]
        lines.append("Top: " + ", ".join(f"{c} {format_money(v)}" for c, v in top))
    if upcoming:
        lines.append("Upcoming (7d): " + ", ".join(
            f"{name} {format_money(amt)} ({d.isoformat()})" for name, amt, d in upcoming))
    return "\n".join(lines)


def process_due_subscriptions(today: dt.date | None = None) -> list[tuple[str, dt.date, float, str]]:
    """Post every due subscription charge and advance its LastCharged.

    Returns a list of (name, due_date, amount, type) that were posted.
    Idempotent: LastCharged only moves forward and is persisted per charge.
    """
    from app.sheets import subscriptions as subs
    from app.sheets.transactions import append_transaction

    if today is None:
        today = now_local().date()

    posted: list[tuple[str, dt.date, float, str]] = []
    for s in subs.list_subscriptions():
        if not s.active:
            continue
        try:
            base = s.last_charged or today
            for due in subs.due_dates_since(base, today, s.frequency, s.day, s.month):
                append_transaction(
                    date=due.strftime("%Y-%m-%d %H:%M"),
                    description=f"{s.name} (auto)",
                    category=s.category, amount=s.amount, txn_type=s.type,
                )
                subs.set_last_charged(s.row, due)
                posted.append((s.name, due, s.amount, s.type))
        except Exception:
            logger.exception("Failed processing subscription %s", s.name)
    return posted


def _format_posted(posted: list[tuple[str, dt.date, float, str]]) -> str:
    lines = ["🔁 *Auto-logged subscriptions:*"]
    for name, due, amount, _type in posted:
        lines.append(f"  • {name} — {format_money(amount)} ({due.isoformat()})")
    return "\n".join(lines)


async def _run_subscription_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    posted = process_due_subscriptions()
    if posted:
        try:
            from app.sheets import dashboard
            dashboard.rebuild_dashboard()
        except Exception:
            logger.exception("Dashboard rebuild after sub-check failed")
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID, text=_format_posted(posted), parse_mode="Markdown",
        )


def register_jobs(application: Application) -> None:
    """Wire subscription jobs onto the application's JobQueue."""
    jq = application.job_queue
    jq.run_once(_run_subscription_check, when=5)  # startup catch-up
    jq.run_daily(_run_subscription_check, time=dt.time(hour=SUB_CHECK_HOUR, tzinfo=TZ))
    logger.info("Registered subscription jobs (startup + daily @ %02d:00)", SUB_CHECK_HOUR)
