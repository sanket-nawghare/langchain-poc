"""Configuration validation tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_safe_local_defaults_require_no_secret() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.api_port == 8000
    assert settings.llm_provider == "fake"
    assert settings.llm_api_key is None


def test_invalid_port_fails_with_an_actionable_field_error() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, api_port=0)

    assert error.value.errors()[0]["loc"] == ("api_port",)


def test_secret_values_are_redacted() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key="do-not-print-this-secret",
    )

    assert "do-not-print-this-secret" not in repr(settings)
    assert "**********" in repr(settings)
