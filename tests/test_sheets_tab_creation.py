"""Every get-or-create helper must tell "the tab is missing" apart from "Google
is briefly down".

A 503 once sent the subscriptions helper down the create path, which would have
left the bot reading a second, empty tab and reporting no subscriptions at all.
"""
import pytest
from gspread.exceptions import WorksheetNotFound

from app.sheets import budgets, dashboard, subscriptions
from tests.conftest import FakeSpreadsheet

# (module, helper, the tab that helper owns)
CASES = [
    (subscriptions, "ensure_subs_tab", subscriptions.SUBS_SHEET),
    (budgets, "ensure_budgets_tab", budgets.BUDGETS_SHEET),
    (dashboard, "_get_or_create_hidden_index", dashboard.INDEX_SHEET),
    (dashboard, "ensure_core_tabs", dashboard.DASHBOARD_SHEET),
]
IDS = [f"{mod.__name__.split('.')[-1]}.{fn}" for mod, fn, _ in CASES]


@pytest.fixture
def run_helper(monkeypatch):
    """Point a helper's module at a fake spreadsheet, then call it."""
    def _run(module, helper, ss):
        monkeypatch.setattr(module, "get_spreadsheet", lambda: ss)
        if hasattr(module, "batch_update"):
            monkeypatch.setattr(module, "batch_update", lambda *a, **k: None)
        return getattr(module, helper)()
    return _run


@pytest.mark.parametrize("module,helper,tab", CASES, ids=IDS)
def test_creates_the_tab_when_it_is_genuinely_missing(module, helper, tab, run_helper):
    ss = FakeSpreadsheet({tab: WorksheetNotFound("nope")})

    run_helper(module, helper, ss)

    assert ss.added == [tab]


@pytest.mark.parametrize("module,helper,tab", CASES, ids=IDS)
def test_propagates_api_errors_instead_of_creating(module, helper, tab, run_helper, api_error):
    ss = FakeSpreadsheet({tab: api_error(503)})

    with pytest.raises(Exception) as excinfo:
        run_helper(module, helper, ss)

    assert excinfo.value.code == 503
    assert ss.added == []
