"""Bounded normalization of read-only FHIR data into patient context."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from app.core.config import Settings
from app.domain.clinical import (
    ClinicalRecordSummary,
    ClinicalSummaryCategory,
    PatientSummary,
)
from app.tools.fhir import (
    FhirClient,
    FhirResource,
    FhirResourceType,
    FhirResponseError,
    validate_fhir_resource_id,
)

MAX_SUMMARY_TEXT_LENGTH = 256


@dataclass(frozen=True)
class _ResourcePlan:
    resource_type: FhirResourceType
    category: ClinicalSummaryCategory
    normalize: Callable[[FhirResource], ClinicalRecordSummary]


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, list):
        return ()
    return cast(Sequence[object], value)


def _text(value: object, *, maximum: int = MAX_SUMMARY_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized[:maximum]


def _path(resource: Mapping[str, object], *parts: str) -> object:
    value: object = resource
    for part in parts:
        mapping = _mapping(value)
        if mapping is None:
            return None
        value = mapping.get(part)
    return value


def _first_text(resource: Mapping[str, object], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = _text(_path(resource, *path))
        if value is not None:
            return value
    return None


def _codeable_concept(value: object) -> tuple[str | None, str | None]:
    concept = _mapping(value)
    if concept is None:
        return None, None

    concept_text = _text(concept.get("text"))
    first_code: str | None = None
    for raw_coding in _sequence(concept.get("coding")):
        coding = _mapping(raw_coding)
        if coding is None:
            continue
        code = _text(coding.get("code"))
        display = _text(coding.get("display"))
        if code is not None and first_code is None:
            first_code = code
        if display is not None:
            return code or first_code, display
    return first_code, concept_text


def _status_from_concept(value: object) -> str | None:
    code, display = _codeable_concept(value)
    return code or display


def _period_start(resource: Mapping[str, object], field: str) -> str | None:
    return _text(_path(resource, field, "start"))


def _quantity(value: object) -> str | None:
    quantity = _mapping(value)
    if quantity is None:
        return None
    raw_number = quantity.get("value")
    if not isinstance(raw_number, (int, float)) or isinstance(raw_number, bool):
        return None
    unit = _text(quantity.get("unit")) or _text(quantity.get("code"))
    rendered = f"{raw_number:g}" if isinstance(raw_number, float) else str(raw_number)
    return rendered if unit is None else f"{rendered} {unit}"


def _observation_component(value: object) -> str | None:
    component = _mapping(value)
    if component is None:
        return None
    _, label = _codeable_concept(component.get("code"))
    measured = _quantity(component.get("valueQuantity"))
    if measured is None:
        _, measured = _codeable_concept(component.get("valueCodeableConcept"))
    if measured is None:
        measured = _text(component.get("valueString"), maximum=128)
    if measured is None:
        return None
    return measured if label is None else f"{label}: {measured}"


def _observation_value(resource: Mapping[str, object]) -> str | None:
    value = _quantity(resource.get("valueQuantity"))
    if value is None:
        _, value = _codeable_concept(resource.get("valueCodeableConcept"))
    if value is None:
        value = _text(resource.get("valueString"), maximum=128)
    if value is None:
        scalar = resource.get("valueBoolean")
        if isinstance(scalar, bool):
            value = str(scalar).lower()
        else:
            scalar = resource.get("valueInteger")
            if isinstance(scalar, int) and not isinstance(scalar, bool):
                value = str(scalar)
    if value is not None:
        return value

    components = [
        normalized
        for raw_component in _sequence(resource.get("component"))[:4]
        if (normalized := _observation_component(raw_component)) is not None
    ]
    if not components:
        return None
    return "; ".join(components)[:MAX_SUMMARY_TEXT_LENGTH]


def _record(
    resource: FhirResource,
    *,
    code_field: str,
    fallback_display: str,
    status: str | None,
    effective_at: str | None,
    value: str | None = None,
) -> ClinicalRecordSummary:
    code, display = _codeable_concept(resource.get(code_field))
    return ClinicalRecordSummary(
        code=code,
        display=display or fallback_display,
        status=status,
        effective_at=effective_at,
        value=value,
    )


def _condition(resource: FhirResource) -> ClinicalRecordSummary:
    status = _status_from_concept(resource.get("clinicalStatus"))
    status = status or _status_from_concept(resource.get("verificationStatus"))
    return _record(
        resource,
        code_field="code",
        fallback_display="Unspecified condition",
        status=status,
        effective_at=_first_text(
            resource,
            ("onsetDateTime",),
            ("recordedDate",),
        ),
    )


def _allergy(resource: FhirResource) -> ClinicalRecordSummary:
    status = _status_from_concept(resource.get("clinicalStatus"))
    status = status or _status_from_concept(resource.get("verificationStatus"))
    return _record(
        resource,
        code_field="code",
        fallback_display="Unspecified allergy",
        status=status,
        effective_at=_first_text(
            resource,
            ("onsetDateTime",),
            ("recordedDate",),
        ),
    )


def _medication(resource: FhirResource) -> ClinicalRecordSummary:
    code, display = _codeable_concept(resource.get("medicationCodeableConcept"))
    if display is None:
        display = _text(_path(resource, "medicationReference", "display"))
    return ClinicalRecordSummary(
        code=code,
        display=display or "Unspecified medication",
        status=_text(resource.get("status")),
        effective_at=_text(resource.get("authoredOn")),
    )


def _encounter(resource: FhirResource) -> ClinicalRecordSummary:
    code: str | None = None
    display: str | None = None
    for raw_type in _sequence(resource.get("type")):
        code, display = _codeable_concept(raw_type)
        if code is not None or display is not None:
            break
    if display is None:
        encounter_class = _mapping(resource.get("class"))
        if encounter_class is not None:
            code = _text(encounter_class.get("code"))
            display = _text(encounter_class.get("display"))
    return ClinicalRecordSummary(
        code=code,
        display=display or "Unspecified encounter",
        status=_text(resource.get("status")),
        effective_at=_period_start(resource, "period"),
    )


def _observation(resource: FhirResource) -> ClinicalRecordSummary:
    return _record(
        resource,
        code_field="code",
        fallback_display="Unspecified observation",
        status=_text(resource.get("status")),
        effective_at=_first_text(
            resource,
            ("effectiveDateTime",),
            ("effectivePeriod", "start"),
            ("issued",),
        ),
        value=_observation_value(resource),
    )


def _procedure(resource: FhirResource) -> ClinicalRecordSummary:
    return _record(
        resource,
        code_field="code",
        fallback_display="Unspecified procedure",
        status=_text(resource.get("status")),
        effective_at=_first_text(
            resource,
            ("performedDateTime",),
            ("performedPeriod", "start"),
        ),
    )


def _diagnostic_report(resource: FhirResource) -> ClinicalRecordSummary:
    return _record(
        resource,
        code_field="code",
        fallback_display="Unspecified diagnostic report",
        status=_text(resource.get("status")),
        effective_at=_first_text(
            resource,
            ("effectiveDateTime",),
            ("effectivePeriod", "start"),
            ("issued",),
        ),
    )


RESOURCE_PLANS = (
    _ResourcePlan("Condition", "conditions", _condition),
    _ResourcePlan("AllergyIntolerance", "allergies", _allergy),
    _ResourcePlan("MedicationRequest", "medications", _medication),
    _ResourcePlan("Encounter", "encounters", _encounter),
    _ResourcePlan("Observation", "observations", _observation),
    _ResourcePlan("Procedure", "procedures", _procedure),
    _ResourcePlan("DiagnosticReport", "diagnostic_reports", _diagnostic_report),
)


def _patient_display_name(patient: FhirResource) -> str | None:
    for raw_name in _sequence(patient.get("name")):
        name = _mapping(raw_name)
        if name is None:
            continue
        text = _text(name.get("text"))
        if text is not None:
            return text
        given = [
            part
            for raw_part in _sequence(name.get("given"))
            if (part := _text(raw_part)) is not None
        ]
        family = _text(name.get("family"))
        assembled = " ".join([*given, *([family] if family else [])])
        if assembled:
            return assembled[:MAX_SUMMARY_TEXT_LENGTH]
    return None


def _sort_records(records: list[ClinicalRecordSummary]) -> None:
    records.sort(key=lambda item: (item.display.casefold(), item.code or ""))
    records.sort(key=lambda item: item.effective_at or "", reverse=True)


class PatientSummaryService:
    """Retrieve and normalize one patient with explicit collection bounds."""

    def __init__(
        self,
        client: FhirClient,
        *,
        max_pages_per_search: int = 5,
        max_records_per_type: int = 100,
    ) -> None:
        if not 1 <= max_pages_per_search <= 20:
            raise ValueError("max pages per FHIR search must be between 1 and 20")
        if not 1 <= max_records_per_type <= 500:
            raise ValueError(
                "max records per FHIR resource type must be between 1 and 500"
            )
        self._client = client
        self._max_pages_per_search = max_pages_per_search
        self._max_records_per_type = max_records_per_type

    async def get(self, patient_id: str) -> PatientSummary:
        """Return minimum-necessary context for one validated FHIR patient ID."""

        validated_id = validate_fhir_resource_id(patient_id)
        patient = await self._client.read("Patient", validated_id)
        if patient.get("resourceType") != "Patient":
            raise FhirResponseError("FHIR patient read returned an unexpected resource")

        results = await asyncio.gather(
            *(self._retrieve(plan, validated_id) for plan in RESOURCE_PLANS)
        )
        collections: dict[str, list[ClinicalRecordSummary]] = {}
        truncated: list[ClinicalSummaryCategory] = []
        for plan, (records, was_truncated) in zip(
            RESOURCE_PLANS,
            results,
            strict=True,
        ):
            _sort_records(records)
            collections[plan.category] = records
            if was_truncated:
                truncated.append(plan.category)

        return PatientSummary(
            patient_id=validated_id,
            display_name=_patient_display_name(patient),
            conditions=collections["conditions"],
            allergies=collections["allergies"],
            medications=collections["medications"],
            encounters=collections["encounters"],
            observations=collections["observations"],
            procedures=collections["procedures"],
            diagnostic_reports=collections["diagnostic_reports"],
            truncated_categories=truncated,
        )

    async def _retrieve(
        self,
        plan: _ResourcePlan,
        patient_id: str,
    ) -> tuple[list[ClinicalRecordSummary], bool]:
        page_size = min(self._max_records_per_type, 100)
        page = await self._client.search(
            plan.resource_type,
            {"patient": patient_id, "_count": str(page_size)},
        )
        resources: list[FhirResource] = []
        seen_cursors: set[str] = set()
        pages_read = 0

        while True:
            pages_read += 1
            remaining = self._max_records_per_type - len(resources)
            resources.extend(page.resources[:remaining])
            over_record_limit = len(page.resources) > remaining
            cursor = page.next_cursor
            if (
                over_record_limit
                or len(resources) >= self._max_records_per_type
                or cursor is None
            ):
                truncated = (
                    over_record_limit
                    or cursor is not None
                    or (page.total is not None and page.total > len(resources))
                )
                break
            if pages_read >= self._max_pages_per_search:
                truncated = True
                break
            if cursor in seen_cursors:
                raise FhirResponseError("FHIR pagination cursor repeated")
            seen_cursors.add(cursor)
            page = await self._client.next_page(plan.resource_type, cursor)

        return [plan.normalize(resource) for resource in resources], truncated


def create_patient_summary_service(
    settings: Settings,
    client: FhirClient,
) -> PatientSummaryService:
    """Create the service from validated application bounds."""

    return PatientSummaryService(
        client,
        max_pages_per_search=settings.fhir_max_pages_per_search,
        max_records_per_type=settings.fhir_max_records_per_type,
    )
