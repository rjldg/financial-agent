"""Google returns 429/5xx sporadically; a single blip must not cost a day's run."""
import pytest

from app.sheets.client import retry_transient


def test_retries_a_transient_error_then_returns_the_result(monkeypatch, api_error):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise api_error(503)
        return "ok"

    assert retry_transient(flaky) == "ok"
    assert len(calls) == 3


def test_backs_off_for_longer_between_each_attempt(monkeypatch, api_error):
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)

    def always_429():
        raise api_error(429)

    with pytest.raises(Exception):
        retry_transient(always_429)

    assert slept == sorted(slept) and len(set(slept)) == len(slept)


def test_reraises_once_the_attempts_run_out(monkeypatch, api_error):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    def always_503():
        calls.append(1)
        raise api_error(503)

    with pytest.raises(Exception) as excinfo:
        retry_transient(always_503)

    assert excinfo.value.code == 503
    assert len(calls) == 3


def test_does_not_retry_a_permission_error(monkeypatch, api_error):
    """403 means the credentials are wrong - retrying just hides the real fault."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    def denied():
        calls.append(1)
        raise api_error(403)

    with pytest.raises(Exception) as excinfo:
        retry_transient(denied)

    assert excinfo.value.code == 403
    assert len(calls) == 1


def test_passes_arguments_through_to_the_wrapped_call(monkeypatch, api_error):
    monkeypatch.setattr("time.sleep", lambda _: None)

    assert retry_transient(lambda a, b=0: a + b, 2, b=3) == 5
