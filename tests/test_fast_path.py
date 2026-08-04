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


def test_hyphen_touching_the_number_is_refused():
    # A minus glued straight to the word ("carwash-50") or floating between
    # spaces ("carwash - 50") reads as a negative amount just as much as
    # "carwash -50" does - none of these should book a positive expense.
    assert try_fast_parse("carwash-50") is None
    assert try_fast_parse("carwash - 50") is None


def test_unicode_dash_touching_the_number_is_refused():
    # iOS/macOS autocorrect a typed " - " into an en dash or em dash, so the
    # same "reads as a negative amount" message can arrive with a different
    # dash character - it must be refused exactly like the ASCII hyphen is.
    assert try_fast_parse("carwash – 50") is None  # en dash, spaced
    assert try_fast_parse("carwash—50") is None  # em dash, glued
    assert try_fast_parse("carwash — 50") is None  # em dash, spaced
    # U+2212 MINUS SIGN is what Google Sheets and most finance apps render a
    # negative number with, so a pasted refund must be refused just as hard.
    assert try_fast_parse("grab −145") is None  # minus sign, glued to amount


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


def test_filler_words_dont_block_the_fast_path():
    # "spent"/"paid"/"for"/"on" carry no category meaning of their own, so a
    # bare merchant dressed up with them should still fast-path.
    txn = try_fast_parse("spent 200 on groceries")
    assert txn is not None and txn.category == "Food"
    txn = try_fast_parse("paid 1500 for rent")
    assert txn is not None and txn.category == "Rent"


def test_bare_merchant_variants_still_fast_path():
    assert try_fast_parse("grab 145") is not None
    assert try_fast_parse("load 100") is not None


def test_context_that_changes_the_category_is_refused():
    # Bare "gas" means vehicle fuel (Transport), but "for cooking" flips it to
    # Utilities - a leftover word the fast path can't read, so it must defer
    # to the model rather than guess wrong.
    assert try_fast_parse("bought gas for cooking 450") is None
    # Bare "grab" means a ride (Transport), but "food delivery" means Food -
    # same story: the leftover context words force a fall-through.
    assert try_fast_parse("grab food delivery 350") is None
