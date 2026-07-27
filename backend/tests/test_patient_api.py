"""Normalized synthetic patient API boundary tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.patients import patient_summary_service
from app.domain.clinical import ClinicalRecordSummary, PatientSummary
from app.main import app
from app.services.patient_summary import PatientSummaryService
from app.tools.fhir import (
    FhirClientError,
    FhirNotFoundError,
    FhirRequestError,
    FhirResponseError,
    FhirTimeoutError,
    FhirUnavailableError,
)


class StubPatientSummaryService:
    def __init__(
        self,
        result: PatientSummary | FhirClientError,
    ) -> None:
        self._result = result

    async def get(self, patient_id: str) -> PatientSummary:
        if isinstance(self._result, FhirClientError):
            raise self._result
        assert patient_id == self._result.patient_id
        return self._result


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


def override_summary_service(
    result: PatientSummary | FhirClientError,
) -> None:
    async def override() -> PatientSummaryService:
        return cast(PatientSummaryService, StubPatientSummaryService(result))

    app.dependency_overrides[patient_summary_service] = override


@pytest.mark.anyio
async def test_returns_normalized_patient_summary_envelope(
    client: AsyncClient,
) -> None:
    override_summary_service(
        PatientSummary(
            patient_id="synthetic-1",
            display_name="Synthetic Example",
            conditions=[
                ClinicalRecordSummary(
                    code="example-code",
                    display="Example condition",
                    status="active",
                )
            ],
            truncated_categories=["observations"],
        )
    )
    try:
        response = await client.get("/api/v1/patients/synthetic-1/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    UUID(payload["request_id"])
    assert payload["data"]["patient_id"] == "synthetic-1"
    assert payload["data"]["conditions"][0]["display"] == "Example condition"
    assert payload["data"]["truncated_categories"] == ["observations"]
    assert "resourceType" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            FhirRequestError("sensitive request detail"),
            400,
            "invalid_patient_id",
        ),
        (
            FhirNotFoundError("sensitive missing detail"),
            404,
            "patient_not_found",
        ),
        (FhirTimeoutError("sensitive timeout detail"), 503, "fhir_timeout"),
        (
            FhirUnavailableError("sensitive unavailable detail"),
            503,
            "fhir_unavailable",
        ),
        (
            FhirResponseError("sensitive upstream payload"),
            502,
            "invalid_fhir_response",
        ),
        (
            FhirClientError("sensitive generic detail"),
            502,
            "fhir_request_failed",
        ),
    ],
)
async def test_maps_fhir_failures_to_safe_api_errors(
    client: AsyncClient,
    error: FhirClientError,
    expected_status: int,
    expected_code: str,
) -> None:
    override_summary_service(error)
    try:
        response = await client.get("/api/v1/patients/synthetic-1/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == expected_status
    payload = response.json()
    UUID(payload["request_id"])
    assert payload["error"]["code"] == expected_code
    assert "sensitive" not in response.text
