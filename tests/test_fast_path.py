from app.fast_path import try_fast_parse


def test_bare_merchant_and_amount_is_parsed():
    txn = try_fast_parse("carwash 250")
    assert txn is not None
    assert txn.amount == 250
    assert txn.category == "Transport"
    assert txn.type == "Expense"
    assert txn.description


def test_amount_may_come_first():
    txn = try_fast_parse("250 carwash")
    assert txn is not None and txn.amount == 250


def test_thousands_separator_is_understood():
    txn = try_fast_parse("meralco 2,400")
    assert txn is not None and txn.amount == 2400


def test_questions_are_refused():
    assert try_fast_parse("how much did i spend on grab") is None
    assert try_fast_parse("did i pay meralco 2400?") is None


def test_multiple_items_are_refused():
    assert try_fast_parse("jollibee 320 and grab 145") is None
    assert try_fast_parse("jollibee 320, grab 145") is None


def test_more_than_one_number_is_refused():
    assert try_fast_parse("grab 145 250") is None


def test_no_number_is_refused():
    assert try_fast_parse("carwash") is None


def test_unknown_merchant_is_refused():
    assert try_fast_parse("widget 200") is None


def test_zero_and_negative_amounts_are_refused():
    assert try_fast_parse("carwash 0") is None
    assert try_fast_parse("carwash -50") is None


def test_amount_glued_to_a_word_is_refused():
    # "jollibee250" hides a second amount inside what looks like a single
    # clean number ("300") - the fast path must not silently drop it.
    assert try_fast_parse("jollibee250, mcdo 300") is None
    assert try_fast_parse("jollibee250 mcdo 300") is None


def test_income_never_takes_the_fast_path():
    # The fast path always writes an Expense, so income must fall through.
    from app.categories import LEXICON
    assert "salary" not in LEXICON
    assert "freelance" not in LEXICON
    assert try_fast_parse("salary 25000") is None
