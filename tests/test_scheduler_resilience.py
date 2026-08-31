"""The daily run must survive Google's momentary failures.

On 2026-08-31 Sheets answered 503 at 08:00, the whole run died, and the Dental
charge silently missed its due date.
"""
from datetime import date

import pytest

from app.models import Subscription
from app.scheduler import process_due_subscriptions
from app.sheets import subscriptions, transactions


def _dental() -> Subscription:
    return Subscription(
        name="Dental", amount=2500.0, category="Health", type="Expense",
        frequency="Monthly", day=31, month=None,
        last_charged=date(2026, 7, 31), active=True, notes="", row=4,
    )


@pytest.fixture
def posted_rows(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(transactions, "append_transaction",
                        lambda **kw: rows.append(kw) or len(rows))
    monkeypatch.setattr(subscriptions, "set_last_charged", lambda row, when: None)
    return rows


def test_a_transient_read_failure_does_not_cost_the_charge(monkeypatch, api_error, posted_rows):
    reads = []

    def flaky_list():
        reads.append(1)
        if len(reads) == 1:
            raise api_error(503)
        return [_dental()]

    monkeypatch.setattr(subscriptions, "list_subscriptions", flaky_list)

    posted = process_due_subscriptions(today=date(2026, 8, 31))

    assert [(name, due) for name, due, _amt, _t in posted] == [("Dental", date(2026, 8, 31))]
    assert posted_rows[0]["date"].startswith("2026-08-31")


def test_a_transient_write_failure_does_not_cost_the_charge(monkeypatch, api_error, posted_rows):
    monkeypatch.setattr(subscriptions, "list_subscriptions", lambda: [_dental()])
    writes = []
    real_append = transactions.append_transaction

    def flaky_append(**kw):
        writes.append(1)
        if len(writes) == 1:
            raise api_error(503)
        return real_append(**kw)

    monkeypatch.setattr(transactions, "append_transaction", flaky_append)

    posted = process_due_subscriptions(today=date(2026, 8, 31))

    assert len(posted) == 1
    assert len(posted_rows) == 1, "the charge must be written exactly once"


def test_a_permission_error_is_not_retried(monkeypatch, api_error, posted_rows):
    reads = []

    def denied():
        reads.append(1)
        raise api_error(403)

    monkeypatch.setattr(subscriptions, "list_subscriptions", denied)

    with pytest.raises(Exception) as excinfo:
        process_due_subscriptions(today=date(2026, 8, 31))

    assert excinfo.value.code == 403
    assert len(reads) == 1
