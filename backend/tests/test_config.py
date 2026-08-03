"""Configuration validation tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_safe_local_defaults_require_no_secret() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.api_port == 8000
    assert settings.fhir_request_timeout_seconds == 5
    assert settings.fhir_max_retries == 2
    assert settings.fhir_retry_backoff_seconds == 0.1
    assert settings.fhir_max_records_per_type == 500
    assert settings.weaviate_grpc_port == 50051
    assert settings.weaviate_request_timeout_seconds == 10
    assert settings.workflow_node_timeout_seconds == 10
    assert settings.workflow_node_max_retries == 1
    assert settings.llm_provider == "fake"
    assert settings.llm_api_key is None


def test_invalid_port_fails_with_an_actionable_field_error() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, api_port=0)

    assert error.value.errors()[0]["loc"] == ("api_port",)


def test_unbounded_fhir_retry_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, fhir_max_retries=4)

    assert error.value.errors()[0]["loc"] == ("fhir_max_retries",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_node_timeout_seconds", 31),
        ("workflow_node_max_retries", 4),
        ("weaviate_grpc_port", 0),
        ("weaviate_request_timeout_seconds", 31),
    ],
)
def test_unbounded_workflow_execution_configuration_is_rejected(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError) as error:
        Settings.model_validate({field: value})

    assert error.value.errors()[0]["loc"] == (field,)


def test_secret_values_are_redacted() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key="do-not-print-this-secret",
    )

    assert "do-not-print-this-secret" not in repr(settings)
    assert "**********" in repr(settings)
