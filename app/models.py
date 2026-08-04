"""Shared data models for the finance agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.categories import CATEGORIES  # noqa: F401  (re-exported for callers)

Category = Literal[
    "Food", "Transport", "Bills", "Salary", "Entertainment", "Shopping",
    "Health", "Utilities", "Rent", "Freelance", "Dating", "Other",
]

TxnType = Literal["Income", "Expense"]


class Transaction(BaseModel):
    """A single financial transaction extracted from natural language."""

    amount: float = Field(..., gt=0, description="The monetary amount (always positive).")
    category: Category = Field(..., description="One of the allowed categories.")
    description: str = Field(..., description="Short human-readable summary.")
    type: TxnType = Field(..., description="'Income' or 'Expense'.")


@dataclass
class MonthlySummary:
    """Computed financial summary for a single month."""

    year_month: str
    total_income: float = 0.0
    total_expenses: float = 0.0
    net_savings: float = 0.0
    carried_forward: float = 0.0
    running_total: float = 0.0
    category_totals: dict[str, float] = field(default_factory=dict)
    transaction_count: int = 0


@dataclass
class Subscription:
    """A recurring transaction definition stored on the Subscriptions tab."""

    name: str
    amount: float
    category: str
    type: str            # "Income" | "Expense"
    frequency: str       # "Monthly" | "Yearly"
    day: int             # day-of-month (1..31)
    month: Optional[int] # 1..12 for Yearly, else None
    last_charged: Optional[date]
    active: bool
    notes: str = ""
    row: Optional[int] = None  # 1-based sheet row, set when read back


@dataclass
class BudgetStatus:
    """Spend-vs-limit status for one category in a month."""

    category: str
    spent: float
    limit: float

    @property
    def ratio(self) -> float:
        return self.spent / self.limit if self.limit else 0.0


from typing import Optional as _Optional  # noqa: E402


class QuerySpec(BaseModel):
    metric: Literal["spend", "income", "net", "count"]
    category: _Optional[str] = None
    period: _Optional[str] = None  # "YYYY-MM"


class RouterResult(BaseModel):
    intent: Literal["log", "query", "unknown"]
    transactions: list[Transaction] = Field(default_factory=list)
    query: _Optional[QuerySpec] = None
