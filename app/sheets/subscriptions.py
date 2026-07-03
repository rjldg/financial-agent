"""Subscriptions tab: pure due-date engine + arg parsing, then Sheets I/O."""
from __future__ import annotations

import calendar
import logging
from datetime import date

logger = logging.getLogger(__name__)

SUBS_SHEET = "⚙ Subscriptions"
SUBS_HEADERS = ["Name", "Amount", "Category", "Type", "Frequency",
                "DayOfMonth", "Month", "LastCharged", "Active", "Notes"]


def clamp_day(year: int, month: int, day: int) -> int:
    """Clamp a day-of-month to the last valid day for that month/year."""
    return min(day, calendar.monthrange(year, month)[1])


def _add_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def next_due_date(last_charged: date, frequency: str, day: int,
                  month: int | None = None) -> date:
    """First due date strictly after `last_charged`."""
    freq = frequency.lower()
    if freq == "monthly":
        y, m = last_charged.year, last_charged.month
        cand = date(y, m, clamp_day(y, m, day))
        if cand > last_charged:
            return cand
        y, m = _add_month(y, m)
        return date(y, m, clamp_day(y, m, day))
    if freq == "yearly":
        if month is None:
            raise ValueError("Yearly subscription requires a month")
        y = last_charged.year
        cand = date(y, month, clamp_day(y, month, day))
        if cand > last_charged:
            return cand
        return date(y + 1, month, clamp_day(y + 1, month, day))
    raise ValueError(f"Unknown frequency: {frequency}")


def due_dates_since(last_charged: date, today: date, frequency: str, day: int,
                    month: int | None = None) -> list[date]:
    """Every due date in (last_charged, today], oldest first."""
    out: list[date] = []
    cur = last_charged
    while True:
        nxt = next_due_date(cur, frequency, day, month)
        if nxt > today:
            break
        out.append(nxt)
        cur = nxt
    return out


def parse_addsub_args(args: list[str]) -> dict:
    """Parse '/addsub <name> <amount> <category> <monthly|yearly> day=<d> [month=<m>] [type=income]'."""
    if len(args) < 4:
        raise ValueError(
            "Usage: /addsub <name> <amount> <category> <monthly|yearly> "
            "day=<d> [month=<m>] [type=income|expense]"
        )
    name = args[0]
    amount = float(args[1])
    category = args[2]
    frequency = args[3].capitalize()
    if frequency not in ("Monthly", "Yearly"):
        raise ValueError("Frequency must be 'monthly' or 'yearly'")
    day: int | None = None
    month: int | None = None
    ttype = "Expense"
    for tok in args[4:]:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        k = k.lower()
        if k == "day":
            day = int(v)
        elif k == "month":
            month = int(v)
        elif k == "type":
            ttype = "Income" if v.lower().startswith("i") else "Expense"
    if day is None:
        raise ValueError("Provide day=<d> (day of month)")
    if frequency == "Yearly" and month is None:
        raise ValueError("Yearly subscriptions need month=<m>")
    if not 1 <= day <= 31:
        raise ValueError("day must be between 1 and 31")
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    return {"name": name, "amount": amount, "category": category, "type": ttype,
            "frequency": frequency, "day": day, "month": month}
