from app.sheets import theme


def test_rgb_converts_hex_to_unit_floats():
    assert theme.rgb("#ffffff") == {"red": 1.0, "green": 1.0, "blue": 1.0}
    black = theme.rgb("#000000")
    assert black == {"red": 0.0, "green": 0.0, "blue": 0.0}


def test_solid_fill_builds_repeatcell_with_fields():
    req = theme.solid_fill(7, 0, 1, 0, 5, "#1e293b", text="#ffffff", bold=True)
    rc = req["repeatCell"]
    assert rc["range"]["sheetId"] == 7
    assert "backgroundColor" in rc["cell"]["userEnteredFormat"]
    assert rc["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True
    assert "textFormat" in rc["fields"] and "backgroundColor" in rc["fields"]


def test_banding_builds_addbanding():
    req = theme.banding(7, 1, 500, 0, 5, "#1e293b", "#f1f5f9")
    br = req["addBanding"]["bandedRange"]
    assert br["range"]["startRowIndex"] == 1
    assert "rowProperties" in br


def test_sign_color_rules_returns_two_custom_formula_rules():
    rules = theme.sign_color_rules(7, 1, 500, amount_col=3, type_col=4)
    assert len(rules) == 2
    cond = rules[0]["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]
    assert cond["type"] == "CUSTOM_FORMULA"


def test_category_tag_rules_one_per_category():
    from app.models import CATEGORIES
    rules = theme.category_tag_rules(7, 1, 500, category_col=2)
    assert len(rules) == len(CATEGORIES)


def test_monthly_theme_requests_is_nonempty_list_of_dicts():
    reqs = theme.monthly_theme_requests(7)
    assert isinstance(reqs, list) and len(reqs) >= 5
    assert all(isinstance(r, dict) for r in reqs)
