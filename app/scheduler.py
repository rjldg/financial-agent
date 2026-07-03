"""Background jobs: subscription catch-up (startup + daily) and weekly digest."""
from __future__ import annotations

import datetime as dt
import logging

from telegram.ext import Application, ContextTypes

from app.config import ALLOWED_USER_ID, SUB_CHECK_HOUR, TZ, now_local
from app.formatting import format_money

logger = logging.getLogger(__name__)


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
