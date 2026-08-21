"""Subscriptions tab: pure due-date engine + arg parsing, then Sheets I/O."""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

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
    """The next due date after `last_charged`.

    Monthly subscriptions land in a LATER month than `last_charged`, never in
    the same one, so a month can never be charged twice.
    """
    freq = frequency.lower()
    if freq == "monthly":
        # Always look to the month after `last_charged`. Returning a date inside
        # that same month would charge twice in one month whenever the day is
        # moved later mid-cycle - which really happened, billing dental twice in
        # one July. New subscriptions get their marker set a month back so their
        # first charge still lands on time; see initial_last_charged.
        y, m = _add_month(last_charged.year, last_charged.month)
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


def initial_last_charged(today: date, day: int) -> date:
    """Where a brand-new subscription's schedule should start.

    next_due_date always looks to the month after this marker, so putting it in
    the previous month lets a subscription whose day is still ahead charge this
    month, while one whose day has already passed waits for the next - and
    neither is ever back-charged for periods before it was added. It is the
    partner of next_due_date's one-charge-per-month rule; neither is correct
    without the other.
    """
    if clamp_day(today.year, today.month, day) > today.day:
        return today.replace(day=1) - timedelta(days=1)
    return today


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

# --- Sheets I/O (append below the pure engine) ---
from app.models import Subscription  # noqa: E402
from app.sheets.client import get_spreadsheet  # noqa: E402


def _row_to_sub(row: list[str], row_index: int) -> Subscription:
    def _int_or_none(v):
        v = (v or "").strip()
        return int(v) if v else None

    lc = (row[7] or "").strip() if len(row) > 7 else ""
    return Subscription(
        name=row[0],
        amount=float(row[1] or 0),
        category=row[2],
        type=row[3] or "Expense",
        frequency=row[4] or "Monthly",
        day=int(row[5] or 1),
        month=_int_or_none(row[6] if len(row) > 6 else ""),
        last_charged=date.fromisoformat(lc) if lc else None,
        active=str(row[8]).strip().upper() == "TRUE" if len(row) > 8 else True,
        notes=row[9] if len(row) > 9 else "",
        row=row_index,
    )


def _sub_fields_to_row(fields: dict, last_charged: date) -> list:
    return [
        fields["name"], fields["amount"], fields["category"], fields["type"],
        fields["frequency"], fields["day"],
        fields["month"] if fields["month"] is not None else "",
        last_charged.isoformat(), "TRUE", fields.get("notes", ""),
    ]


def ensure_subs_tab():
    ss = get_spreadsheet()
    try:
        return ss.worksheet(SUBS_SHEET)
    except Exception:
        ws = ss.add_worksheet(title=SUBS_SHEET, rows=200, cols=len(SUBS_HEADERS))
        ws.update("A1", [SUBS_HEADERS], value_input_option="USER_ENTERED")
        return ws


def list_subscriptions() -> list[Subscription]:
    ws = ensure_subs_tab()
    subs: list[Subscription] = []
    for i, row in enumerate(ws.get_all_values()[1:], start=2):
        if row and row[0].strip():
            try:
                subs.append(_row_to_sub(row, i))
            except (ValueError, IndexError):
                logger.exception("Bad subscription row %d: %r", i, row)
    return subs


def add_subscription(fields: dict, last_charged: date) -> None:
    ws = ensure_subs_tab()
    ws.append_row(_sub_fields_to_row(fields, last_charged),
                  value_input_option="USER_ENTERED")


def _find_row(name: str) -> int | None:
    for s in list_subscriptions():
        if s.name.lower() == name.lower():
            return s.row
    return None


def remove_subscription(name: str) -> bool:
    ws = ensure_subs_tab()
    row = _find_row(name)
    if row is None:
        return False
    ws.delete_rows(row)
    return True


def toggle_subscription(name: str) -> bool | None:
    """Flip Active; return the new state, or None if not found."""
    ws = ensure_subs_tab()
    for s in list_subscriptions():
        if s.name.lower() == name.lower():
            new_state = not s.active
            ws.update_cell(s.row, 9, "TRUE" if new_state else "FALSE")
            return new_state
    return None


def set_last_charged(row: int, when: date) -> None:
    ensure_subs_tab().update_cell(row, 8, when.isoformat())


def upcoming_subscriptions(today: date, days: int = 30) -> list[tuple[Subscription, date]]:
    """Active subscriptions whose next charge falls within `days` of `today`."""
    from datetime import timedelta
    horizon = today + timedelta(days=days)
    out: list[tuple[Subscription, date]] = []
    for s in list_subscriptions():
        if not s.active:
            continue
        base = s.last_charged or today
        nxt = next_due_date(base, s.frequency, s.day, s.month)
        if today <= nxt <= horizon:
            out.append((s, nxt))
    return sorted(out, key=lambda t: t[1])
