"""Minimum-necessary patient summary retrieval and normalization tests."""

from __future__ import annotations

from typing import cast

import pytest

from app.services.patient_summary import PatientSummaryService
from app.tools.fhir import (
    FhirNotFoundError,
    FhirRequestError,
    FhirResource,
    FhirResourceType,
    FhirResponseError,
    FhirSearchPage,
    FhirSearchParams,
)


def resource(**values: object) -> FhirResource:
    return cast(FhirResource, values)


class FakeFhirClient:
    def __init__(
        self,
        *,
        patient: FhirResource | None = None,
        first_pages: dict[FhirResourceType, FhirSearchPage] | None = None,
        next_pages: dict[tuple[FhirResourceType, str], FhirSearchPage] | None = None,
    ) -> None:
        self.patient = patient
        self.first_pages = first_pages or {}
        self.next_pages = next_pages or {}
        self.searches: list[tuple[FhirResourceType, FhirSearchParams]] = []
        self.next_requests: list[tuple[FhirResourceType, str]] = []

    async def read(
        self,
        resource_type: FhirResourceType,
        resource_id: str,
    ) -> FhirResource:
        assert resource_type == "Patient"
        if self.patient is None:
            raise FhirNotFoundError("FHIR resource was not found")
        return self.patient

    async def search(
        self,
        resource_type: FhirResourceType,
        parameters: FhirSearchParams,
    ) -> FhirSearchPage:
        self.searches.append((resource_type, parameters))
        return self.first_pages.get(
            resource_type,
            FhirSearchPage(resources=(), total=0, next_cursor=None),
        )

    async def next_page(
        self,
        resource_type: FhirResourceType,
        cursor: str,
    ) -> FhirSearchPage:
        self.next_requests.append((resource_type, cursor))
        return self.next_pages[(resource_type, cursor)]

    async def aclose(self) -> None:
        return None


def page(
    *resources: FhirResource,
    next_cursor: str | None = None,
) -> FhirSearchPage:
    return FhirSearchPage(
        resources=resources,
        total=len(resources),
        next_cursor=next_cursor,
    )


@pytest.mark.anyio
async def test_normalizes_all_supported_patient_summary_categories() -> None:
    client = FakeFhirClient(
        patient=resource(
            resourceType="Patient",
            id="synthetic-1",
            name=[{"given": ["Ada", "M"], "family": "Example"}],
            address=[{"text": "must not escape"}],
        ),
        first_pages={
            "Condition": page(
                resource(
                    code={"coding": [{"code": "44054006", "display": "Diabetes"}]},
                    clinicalStatus={"coding": [{"code": "active"}]},
                    onsetDateTime="2020-01-02",
                )
            ),
            "AllergyIntolerance": page(
                resource(
                    code={"text": "Peanut allergy"},
                    verificationStatus={"coding": [{"code": "confirmed"}]},
                    recordedDate="2021-02-03",
                )
            ),
            "MedicationRequest": page(
                resource(
                    medicationReference={"display": "Example medicine"},
                    status="active",
                    authoredOn="2024-03-04",
                )
            ),
            "Encounter": page(
                resource(
                    type=[{"coding": [{"code": "AMB", "display": "Ambulatory"}]}],
                    status="finished",
                    period={"start": "2025-04-05"},
                )
            ),
            "Observation": page(
                resource(
                    code={"text": "Blood pressure"},
                    status="final",
                    effectiveDateTime="2025-05-06",
                    component=[
                        {
                            "code": {"text": "Systolic"},
                            "valueQuantity": {"value": 120, "unit": "mmHg"},
                        },
                        {
                            "code": {"text": "Diastolic"},
                            "valueQuantity": {"value": 80, "unit": "mmHg"},
                        },
                    ],
                    note=[{"text": "must not escape"}],
                )
            ),
            "Procedure": page(
                resource(
                    code={"coding": [{"code": "80146002"}], "text": "Appendectomy"},
                    status="completed",
                    performedPeriod={"start": "2019-06-07"},
                )
            ),
            "DiagnosticReport": page(
                resource(
                    code={"coding": [{"code": "58410-2", "display": "CBC"}]},
                    status="final",
                    issued="2025-07-08T09:00:00Z",
                    conclusion="must not escape",
                )
            ),
        },
    )

    summary = await PatientSummaryService(client).get("synthetic-1")

    assert summary.display_name == "Ada M Example"
    assert summary.conditions[0].model_dump() == {
        "code": "44054006",
        "display": "Diabetes",
        "status": "active",
        "effective_at": "2020-01-02",
        "value": None,
    }
    assert summary.allergies[0].display == "Peanut allergy"
    assert summary.medications[0].display == "Example medicine"
    assert summary.encounters[0].code == "AMB"
    assert summary.observations[0].value == ("Systolic: 120 mmHg; Diastolic: 80 mmHg")
    assert summary.procedures[0].display == "Appendectomy"
    assert summary.diagnostic_reports[0].code == "58410-2"
    assert summary.truncated_categories == []

    serialized = summary.model_dump(mode="json")
    serialized_text = str(serialized)
    assert "resourceType" not in serialized_text
    assert "must not escape" not in serialized_text
    assert len(client.searches) == 7
    assert all(parameters["_count"] == "100" for _, parameters in client.searches)


@pytest.mark.anyio
async def test_missing_and_variant_optional_fields_produce_safe_partial_summary() -> (
    None
):
    client = FakeFhirClient(
        patient=resource(resourceType="Patient", id="synthetic-1"),
        first_pages={
            "Observation": page(
                resource(
                    code=[],
                    status={"unexpected": "shape"},
                    effectivePeriod={"start": 42},
                    valueBoolean=True,
                )
            ),
            "Condition": page(resource()),
        },
    )

    summary = await PatientSummaryService(client).get("synthetic-1")

    assert summary.display_name is None
    assert summary.conditions[0].display == "Unspecified condition"
    assert summary.observations[0].model_dump() == {
        "code": None,
        "display": "Unspecified observation",
        "status": None,
        "effective_at": None,
        "value": "true",
    }
    assert summary.allergies == []
    assert summary.medications == []
    assert summary.encounters == []
    assert summary.procedures == []
    assert summary.diagnostic_reports == []


@pytest.mark.anyio
async def test_follows_pages_and_reports_collection_truncation() -> None:
    client = FakeFhirClient(
        patient=resource(resourceType="Patient", id="synthetic-1"),
        first_pages={
            "Observation": page(
                resource(code={"text": "Old"}, effectiveDateTime="2020-01-01"),
                resource(code={"text": "Newest"}, effectiveDateTime="2024-01-01"),
                next_cursor="page-2",
            )
        },
        next_pages={
            ("Observation", "page-2"): page(
                resource(code={"text": "Middle"}, effectiveDateTime="2022-01-01"),
                resource(code={"text": "Excluded"}, effectiveDateTime="2021-01-01"),
                next_cursor="page-3",
            )
        },
    )

    summary = await PatientSummaryService(
        client,
        max_records_per_type=3,
    ).get("synthetic-1")

    assert [record.display for record in summary.observations] == [
        "Newest",
        "Middle",
        "Old",
    ]
    assert summary.truncated_categories == ["observations"]
    assert client.next_requests == [("Observation", "page-2")]


@pytest.mark.anyio
async def test_stops_at_page_bound_and_reports_truncation() -> None:
    client = FakeFhirClient(
        patient=resource(resourceType="Patient", id="synthetic-1"),
        first_pages={
            "Procedure": page(
                resource(code={"text": "First"}),
                next_cursor="page-2",
            )
        },
    )

    summary = await PatientSummaryService(
        client,
        max_pages_per_search=1,
    ).get("synthetic-1")

    assert [record.display for record in summary.procedures] == ["First"]
    assert summary.truncated_categories == ["procedures"]
    assert client.next_requests == []


@pytest.mark.anyio
async def test_rejects_repeated_pagination_cursor() -> None:
    client = FakeFhirClient(
        patient=resource(resourceType="Patient", id="synthetic-1"),
        first_pages={
            "Condition": page(resource(code={"text": "One"}), next_cursor="same")
        },
        next_pages={
            ("Condition", "same"): page(
                resource(code={"text": "Two"}),
                next_cursor="same",
            )
        },
    )

    with pytest.raises(FhirResponseError, match="cursor repeated"):
        await PatientSummaryService(client).get("synthetic-1")


@pytest.mark.anyio
async def test_validates_patient_id_and_propagates_not_found() -> None:
    client = FakeFhirClient()
    service = PatientSummaryService(client)

    with pytest.raises(FhirRequestError, match="invalid FHIR resource ID"):
        await service.get("unsafe/id")
    with pytest.raises(FhirNotFoundError, match="not found"):
        await service.get("synthetic-1")
    assert client.searches == []
