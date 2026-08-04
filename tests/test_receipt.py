from app.llm_parser import parse_receipt_response
from app.models import Transaction


def test_parse_receipt_response_returns_transaction():
    js = '{"amount": 349.5, "category": "Food", "description": "Jollibee", "type": "Expense"}'
    txn = parse_receipt_response(js)
    assert isinstance(txn, Transaction) and txn.amount == 349.5 and txn.category == "Food"


def test_parse_receipt_response_strips_fences():
    js = '```json\n{"amount": 100, "category": "Shopping", "description": "Uniqlo", "type": "Expense"}\n```'
    txn = parse_receipt_response(js)
    assert txn.category == "Shopping"
