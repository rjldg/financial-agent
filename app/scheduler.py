"""Background jobs: subscription catch-up (startup + daily) and weekly digest."""
from __future__ import annotations

import datetime as dt
import logging

from telegram.ext import Application, ContextTypes

from app.config import ALLOWED_USER_ID, SUB_CHECK_HOUR, TZ, WEEKLY_DIGEST_DAY, WEEKLY_DIGEST_HOUR, now_local
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


def build_weekly_digest(today: dt.date | None = None) -> str:
    from app.sheets.subscriptions import upcoming_subscriptions
    from app.sheets.transactions import get_month_records
    if today is None:
        today = now_local().date()
    records = get_month_records(today.strftime("%Y-%m"))
    # include previous month too if the 7-day window crosses a boundary
    if (today - dt.timedelta(days=7)).month != today.month:
        prev = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
        records = get_month_records(prev) + records
    total, by_cat = filter_recent_expense(records, today, days=7)
    upcoming = [(s.name, s.amount, when) for s, when in upcoming_subscriptions(today, days=7)]
    return compose_weekly_digest(total, by_cat, upcoming, today)


async def _run_weekly_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only fire on the configured weekday (avoids run_daily day-index ambiguity).
    if now_local().strftime("%a").lower() != WEEKLY_DIGEST_DAY.lower()[:3]:
        return
    try:
        text = build_weekly_digest()
    except Exception:
        logger.exception("Weekly digest build failed")
        return
    await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=text, parse_mode="Markdown")


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


# APScheduler throws away a job that starts later than its grace period, and the
# default is a single second — enough for every daily run to be dropped when the
# machine is momentarily busy. These jobs work out for themselves what they still
# owe and are safe to repeat, so a late run must never be skipped.
_NEVER_SKIP = {"misfire_grace_time": None}


def register_jobs(application: Application) -> None:
    """Wire subscription jobs onto the application's JobQueue."""
    jq = application.job_queue
    if jq is None:
        logger.warning(
            "JobQueue is unavailable — automatic subscription catch-up and the weekly "
            "digest will NOT run. Install the extra: "
            'pip install "python-telegram-bot[job-queue]" (or pip install -r requirements.txt).'
        )
        return
    jq.run_once(_run_subscription_check, when=5, job_kwargs=_NEVER_SKIP)  # startup catch-up
    jq.run_daily(_run_subscription_check, time=dt.time(hour=SUB_CHECK_HOUR, tzinfo=TZ),
                 job_kwargs=_NEVER_SKIP)
    jq.run_daily(_run_weekly_digest, time=dt.time(hour=WEEKLY_DIGEST_HOUR, tzinfo=TZ),
                 job_kwargs=_NEVER_SKIP)
    logger.info("Registered subscription jobs (startup + daily @ %02d:00)", SUB_CHECK_HOUR)
