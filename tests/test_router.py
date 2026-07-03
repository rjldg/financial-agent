from app.llm_parser import parse_router_response
from app.models import RouterResult


def test_parse_single_log():
    js = '{"intent":"log","transactions":[{"amount":150,"category":"Food","description":"McDo","type":"Expense"}]}'
    r = parse_router_response(js)
    assert isinstance(r, RouterResult)
    assert r.intent == "log" and len(r.transactions) == 1
    assert r.transactions[0].category == "Food"


def test_parse_multi_item_with_fences():
    js = '```json\n{"intent":"log","transactions":[' \
         '{"amount":150,"category":"Food","description":"lunch","type":"Expense"},' \
         '{"amount":90,"category":"Transport","description":"grab","type":"Expense"}]}\n```'
    r = parse_router_response(js)
    assert len(r.transactions) == 2 and r.transactions[1].amount == 90


def test_parse_query():
    js = '{"intent":"query","query":{"metric":"spend","category":"Food","period":null}}'
    r = parse_router_response(js)
    assert r.intent == "query" and r.query.metric == "spend" and r.query.category == "Food"


def test_parse_unknown():
    r = parse_router_response('{"intent":"unknown"}')
    assert r.intent == "unknown" and r.transactions == []
