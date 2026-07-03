from app.llm_parser import build_image_data_uri, parse_receipt_response
from app.models import Transaction


def test_build_image_data_uri_prefix():
    uri = build_image_data_uri(b"hello", mime="image/png")
    assert uri.startswith("data:image/png;base64,")
    assert uri.endswith("aGVsbG8=")  # base64 of "hello"


def test_parse_receipt_response_returns_transaction():
    js = '{"amount": 349.5, "category": "Food", "description": "Jollibee", "type": "Expense"}'
    txn = parse_receipt_response(js)
    assert isinstance(txn, Transaction) and txn.amount == 349.5 and txn.category == "Food"


def test_parse_receipt_response_strips_fences():
    js = '```json\n{"amount": 100, "category": "Shopping", "description": "Uniqlo", "type": "Expense"}\n```'
    txn = parse_receipt_response(js)
    assert txn.category == "Shopping"
