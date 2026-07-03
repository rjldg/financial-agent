"""Currency formatting helpers shared by the sheets and bot layers."""
from __future__ import annotations

from app.config import CURRENCY_SYMBOL


def format_money(amount: float, *, signed: bool = False) -> str:
    """Format a number as currency, e.g. 48000 -> '₱48,000.00'.

    When ``signed`` is True a leading '+'/'-' is added and the symbol follows it
    (e.g. '+₱48,000.00', '-₱150.00'). When False, a negative simply keeps the
    minus before the symbol.
    """
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}{CURRENCY_SYMBOL}{abs(amount):,.2f}"
    if amount < 0:
        return f"-{CURRENCY_SYMBOL}{abs(amount):,.2f}"
    return f"{CURRENCY_SYMBOL}{amount:,.2f}"
