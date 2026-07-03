"""Pure composition of query answers, insights, and search matching."""
from __future__ import annotations

from app.formatting import format_money
from app.models import MonthlySummary


def compose_query_answer(summary: MonthlySummary, metric: str,
                         category: str | None, period: str) -> str:
    if metric == "spend" and category:
        val = summary.category_totals.get(category, 0.0)
        return f"You spent {format_money(val)} on {category} in {period}."
    if metric == "spend":
        return f"You spent {format_money(summary.total_expenses)} in {period}."
    if metric == "income":
        return f"You earned {format_money(summary.total_income)} in {period}."
    if metric == "net":
        return f"Your net savings for {period} were {format_money(summary.net_savings)}."
    if metric == "count":
        return f"You logged {summary.transaction_count} transactions in {period}."
    return (f"{period}: income {format_money(summary.total_income)}, "
            f"expenses {format_money(summary.total_expenses)}.")


def compose_insights(current: MonthlySummary,
                     previous: MonthlySummary | None = None) -> str:
    lines = [f"📈 *Insights · {current.year_month}*"]
    spend_cats = [(c, v) for c, v in current.category_totals.items() if c != "Salary"]
    if spend_cats:
        top = sorted(spend_cats, key=lambda kv: -kv[1])[:3]
        lines.append("Top spending: " + ", ".join(f"{c} {format_money(v)}" for c, v in top))
    lines.append(f"Net this month: {format_money(current.net_savings)}")
    if previous:
        diff = current.total_expenses - previous.total_expenses
        arrow = "↑" if diff > 0 else "↓"
        lines.append(f"Expenses {arrow} {format_money(abs(diff))} vs {previous.year_month}")
    return "\n".join(lines)


def row_matches(description: str, category: str, term: str) -> bool:
    term_l = term.lower()
    return term_l in (description or "").lower() or term_l in (category or "").lower()
