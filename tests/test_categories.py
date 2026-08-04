from typing import get_args

from app.categories import (
    CATEGORIES,
    CATEGORY_GUIDE,
    LEXICON,
    classify_by_lexicon,
    render_category_guide,
)
from app.models import Category


def test_the_four_category_lists_cannot_drift_apart():
    # A Literal must be static, so the type system cannot enforce this. A test does.
    assert set(CATEGORIES) == set(get_args(Category))
    assert set(CATEGORIES) == set(CATEGORY_GUIDE)
    assert set(LEXICON.values()) <= set(CATEGORIES)


def test_every_category_has_a_meaning():
    for name, meaning in CATEGORY_GUIDE.items():
        assert meaning.strip(), f"{name} has no meaning for the model to read"


def test_render_category_guide_lists_every_category():
    rendered = render_category_guide()
    for name in CATEGORIES:
        assert name in rendered


def test_known_merchants_resolve():
    assert classify_by_lexicon("carwash 250") == "Transport"
    assert classify_by_lexicon("meralco 2400") == "Utilities"
    assert classify_by_lexicon("jollibee 320") == "Food"
    assert classify_by_lexicon("load 100") == "Bills"
    assert classify_by_lexicon("haircut 150") == "Health"


def test_unknown_text_resolves_to_nothing():
    assert classify_by_lexicon("bought a widget 200") is None
    assert classify_by_lexicon("") is None


def test_matches_whole_words_only():
    # "load" must not fire inside "download"
    assert classify_by_lexicon("download 100") is None


def test_two_categories_in_one_message_is_refused():
    # Too mixed to pin down; Tier 1 should decide instead.
    assert classify_by_lexicon("jollibee and grab") is None
