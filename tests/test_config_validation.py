from app.config import validate_config


def test_validate_config_flags_missing_credentials_file():
    # conftest sets a dummy token/sheet, but service_account.json won't exist in CI.
    problems = validate_config()
    assert any("credential" in p.lower() or "service_account" in p.lower() for p in problems)
