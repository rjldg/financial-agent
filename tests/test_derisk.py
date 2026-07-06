"""Tests for the de-risking hardening: config flags, timezone fallback surface,
theme banding toggle, scheduler job-queue guard, and retheme batching."""
from unittest.mock import MagicMock, patch

from app.config import _flag
from app.sheets import theme
from app.sheets import transactions as tx
from app import scheduler


# --- config feature flags ---

def test_flag_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("X_TEST_FLAG", raising=False)
    assert _flag("X_TEST_FLAG", True) is True
    assert _flag("X_TEST_FLAG", False) is False


def test_flag_falsy_values(monkeypatch):
    for falsy in ("0", "false", "FALSE", "no", "off", ""):
        monkeypatch.setenv("X_TEST_FLAG", falsy)
        assert _flag("X_TEST_FLAG", True) is False


def test_flag_truthy_values(monkeypatch):
    for truthy in ("1", "true", "yes", "on", "anything"):
        monkeypatch.setenv("X_TEST_FLAG", truthy)
        assert _flag("X_TEST_FLAG", False) is True


# --- theme banding toggle ---

def test_monthly_theme_requests_banding_toggle():
    with_b = theme.monthly_theme_requests(7)
    without_b = theme.monthly_theme_requests(7, include_banding=False)
    assert any("addBanding" in r for r in with_b)
    assert not any("addBanding" in r for r in without_b)
    assert len(without_b) == len(with_b) - 1


# --- scheduler guard ---

def test_register_jobs_handles_missing_job_queue():
    app = MagicMock()
    app.job_queue = None
    scheduler.register_jobs(app)  # must not raise when JobQueue is unavailable


def test_register_jobs_wires_three_jobs_when_available():
    app = MagicMock()
    jq = MagicMock()
    app.job_queue = jq
    scheduler.register_jobs(app)
    assert jq.run_once.call_count == 1
    assert jq.run_daily.call_count == 2


# --- retheme batching ---

def test_retheme_monthly_tab_applies_theme_then_banding_separately():
    ws = MagicMock()
    ws.id = 7
    ws.title = "2026-03"
    with patch.object(tx, "batch_update") as bu, \
         patch.object(tx, "_existing_cf_rule_count", return_value=0):
        tx.retheme_monthly_tab(ws)
    assert bu.call_count == 2
    first_reqs = bu.call_args_list[0].args[0]
    assert not any("addBanding" in r for r in first_reqs)
    second_reqs = bu.call_args_list[1].args[0]
    assert any("addBanding" in r for r in second_reqs)


def test_retheme_monthly_tab_swallows_banding_error():
    ws = MagicMock()
    ws.id = 7
    ws.title = "2026-03"
    with patch.object(tx, "batch_update", side_effect=[None, Exception("overlap")]) as bu, \
         patch.object(tx, "_existing_cf_rule_count", return_value=0):
        tx.retheme_monthly_tab(ws)  # must not raise even if banding fails
    assert bu.call_count == 2


def test_retheme_monthly_tab_clears_existing_cf_rules_first():
    """Idempotency: pre-existing conditional-format rules are deleted before re-adding."""
    ws = MagicMock()
    ws.id = 7
    ws.title = "2026-03"
    with patch.object(tx, "batch_update") as bu, \
         patch.object(tx, "_existing_cf_rule_count", return_value=3):
        tx.retheme_monthly_tab(ws)
    first_reqs = bu.call_args_list[0].args[0]
    deletes = [r for r in first_reqs if "deleteConditionalFormatRule" in r]
    # 3 existing rules -> 3 deletes, highest index first (2,1,0)
    assert [r["deleteConditionalFormatRule"]["index"] for r in deletes] == [2, 1, 0]


def test_existing_cf_rule_count_is_zero_on_metadata_failure():
    ss = MagicMock()
    ss.fetch_sheet_metadata.side_effect = Exception("no access")
    with patch.object(tx, "get_spreadsheet", return_value=ss):
        assert tx._existing_cf_rule_count(7) == 0


def test_retheme_existing_tabs_counts_successes():
    ss = MagicMock()
    ss.worksheet.side_effect = lambda ym: MagicMock(id=1, title=ym)
    with patch.object(tx, "get_spreadsheet", return_value=ss), \
         patch.object(tx, "list_monthly_sheets", return_value=["2026-01", "2026-02"]), \
         patch.object(tx, "retheme_monthly_tab") as rt:
        n = tx.retheme_existing_tabs()
    assert n == 2 and rt.call_count == 2
