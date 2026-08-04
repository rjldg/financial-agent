from app.categories import CATEGORIES
from app.llm_parser import parse_router_response, render_router_prompt, router_schema
from app.models import RouterResult


def test_schema_is_generated_from_the_model_not_hand_written():
    schema = router_schema()
    # Hand-writing this is how the query object went missing during design.
    assert set(schema["properties"]) == {"intent", "transactions", "query"}


def test_schema_pins_the_category_enum():
    schema = router_schema()
    txn = schema["$defs"]["Transaction"]
    assert txn["properties"]["category"]["enum"] == CATEGORIES


def test_prompt_carries_every_category_meaning():
    prompt = render_router_prompt()
    for name in CATEGORIES:
        assert name in prompt


def test_prompt_teaches_the_three_intents():
    prompt = render_router_prompt()
    for shape in ('"intent":"log"', '"intent":"query"', '"intent":"unknown"'):
        assert shape in prompt


def test_prompt_shows_a_multi_item_example():
    # Single-item-only examples made the model collapse two spends into one.
    prompt = render_router_prompt()
    assert prompt.count('"amount"') >= 3


def test_parse_router_response_handles_fences():
    js = ('```json\n{"intent":"log","transactions":[{"amount":150,'
          '"category":"Food","description":"lunch","type":"Expense"}]}\n```')
    result = parse_router_response(js)
    assert isinstance(result, RouterResult)
    assert result.transactions[0].category == "Food"
