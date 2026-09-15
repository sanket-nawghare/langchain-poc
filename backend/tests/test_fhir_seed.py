"""Local HAPI seed safeguard tests."""

from typing import Any

import pytest
from scripts.fhir_seed import (
    FhirSeedError,
    _verify_bundle_response,
    idempotent_transaction,
    validate_local_base_url,
)


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("http://127.0.0.1:8080/fhir", "http://127.0.0.1:8080/fhir"),
        ("http://localhost:9080/fhir/", "http://localhost:9080/fhir"),
    ],
)
def test_accepts_explicit_loopback_fhir_targets(
    raw_url: str,
    expected: str,
) -> None:
    assert validate_local_base_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://127.0.0.1:8080/fhir",
        "http://hapi.example.com:8080/fhir",
        "http://127.0.0.1/fhir",
        "http://127.0.0.1:8080/",
        "http://user@127.0.0.1:8080/fhir",
        "http://127.0.0.1:8080/fhir?unsafe=true",
    ],
)
def test_rejects_non_local_or_ambiguous_fhir_targets(raw_url: str) -> None:
    with pytest.raises(FhirSeedError, match="restricted"):
        validate_local_base_url(raw_url)


def test_requires_complete_successful_transaction_response() -> None:
    response: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [
            {"response": {"status": "201 Created"}},
            {"response": {"status": "200 OK"}},
        ],
    }

    assert _verify_bundle_response(response, 2, "transaction") == (1, 1)

    response["entry"][1]["response"]["status"] = "400 Bad Request"
    with pytest.raises(FhirSeedError, match="failed entry"):
        _verify_bundle_response(response, 2, "transaction")


def test_converts_patient_transaction_entries_to_idempotent_puts() -> None:
    source: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "synthetic-patient",
                },
                "request": {
                    "method": "POST",
                    "url": "Patient",
                },
            }
        ],
    }

    transformed = idempotent_transaction(source)

    assert transformed["entry"][0]["request"] == {
        "method": "PUT",
        "url": "Patient/synthetic-patient",
    }
    assert source["entry"][0]["request"]["method"] == "POST"
