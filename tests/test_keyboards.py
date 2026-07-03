from app.bot.keyboards import parse_callback, quick_fix_keyboard, category_picker_keyboard
from app.models import CATEGORIES


def test_parse_callback_basic():
    assert parse_callback("del|2026-03|5") == ("del", "2026-03", 5, None)


def test_parse_callback_with_extra():
    assert parse_callback("setcat|2026-03|5|Food") == ("setcat", "2026-03", 5, "Food")


def test_quick_fix_keyboard_has_three_actions():
    kb = quick_fix_keyboard("2026-03", 5)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(d.startswith("fixcat|") for d in datas)
    assert any(d.startswith("type|") for d in datas)
    assert any(d.startswith("del|") for d in datas)


def test_category_picker_has_all_categories():
    kb = category_picker_keyboard("2026-03", 5)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    setcats = [d for d in datas if d.startswith("setcat|")]
    assert len(setcats) == len(CATEGORIES)
    assert any(d.endswith("|Food") for d in setcats)
