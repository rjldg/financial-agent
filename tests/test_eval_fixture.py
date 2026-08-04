import json
import pathlib

from app.categories import CATEGORIES

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "router_eval.jsonl"
VALID_INTENTS = {"log", "query", "unknown"}
VALID_METRICS = {"spend", "income", "net", "count"}


def _records():
    with FIXTURE.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_fixture_is_big_enough_to_mean_something():
    assert len(_records()) >= 120


def test_every_record_is_well_formed():
    for rec in _records():
        assert rec["text"].strip(), rec
        assert rec["intent"] in VALID_INTENTS, rec
        for txn in rec["transactions"]:
            assert txn["category"] in CATEGORIES, rec
            assert txn["type"] in {"Income", "Expense"}, rec
            assert float(txn["amount"]) > 0, rec
        if rec["query"] is not None:
            assert rec["query"]["metric"] in VALID_METRICS, rec


def test_log_records_carry_transactions_and_others_do_not():
    for rec in _records():
        if rec["intent"] == "log":
            assert rec["transactions"], rec
        else:
            assert rec["transactions"] == [], rec


def test_query_records_carry_a_query_object():
    for rec in _records():
        assert (rec["query"] is not None) == (rec["intent"] == "query"), rec


def test_the_measured_failures_are_covered():
    texts = {rec["text"] for rec in _records()}
    for required in ("carwash 250", "load 100", "meralco 2400", "haircut 150"):
        assert required in texts
