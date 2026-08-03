"""Deterministic minimum-necessary context selection for grounded generation."""

import re

from pydantic import ValidationError

from app.domain.clinical import (
    Citation,
    ClinicalRecordSummary,
    ClinicalSummaryCategory,
    PatientSummary,
)
from app.domain.generation import (
    MAX_GROUNDED_FACTS,
    GroundedClinicalFact,
    GroundedEvidence,
    GroundedGenerationRequest,
    GroundedPatientContext,
)
from app.tools.response import ResponseGenerationInputError

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CATEGORY_PRIORITY: dict[ClinicalSummaryCategory, int] = {
    "allergies": 7,
    "medications": 6,
    "conditions": 5,
    "observations": 4,
    "diagnostic_reports": 3,
    "procedures": 2,
    "encounters": 1,
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in TOKEN_PATTERN.findall(value.casefold()) if len(token) >= 3
    }


def _record_text(record: ClinicalRecordSummary) -> str:
    return " ".join(
        value
        for value in (
            record.code,
            record.display,
            record.status,
            record.effective_at,
            record.value,
        )
        if value is not None
    )


def _selected_records(
    query: str,
    patient: PatientSummary,
) -> list[tuple[ClinicalSummaryCategory, ClinicalRecordSummary]]:
    records_by_category: tuple[
        tuple[ClinicalSummaryCategory, list[ClinicalRecordSummary]], ...
    ] = (
        ("allergies", patient.allergies),
        ("medications", patient.medications),
        ("conditions", patient.conditions),
        ("observations", patient.observations),
        ("diagnostic_reports", patient.diagnostic_reports),
        ("procedures", patient.procedures),
        ("encounters", patient.encounters),
    )
    query_tokens = _tokens(query)
    ranked: list[
        tuple[int, int, int, ClinicalSummaryCategory, ClinicalRecordSummary]
    ] = []
    ordinal = 0
    for category, records in records_by_category:
        for record in records:
            overlap = len(query_tokens & _tokens(_record_text(record)))
            ranked.append(
                (
                    overlap,
                    CATEGORY_PRIORITY[category],
                    ordinal,
                    category,
                    record,
                )
            )
            ordinal += 1
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [(category, record) for _, _, _, category, record in ranked][
        :MAX_GROUNDED_FACTS
    ]


def _clinical_fact(
    category: ClinicalSummaryCategory,
    record: ClinicalRecordSummary,
) -> GroundedClinicalFact:
    def bounded(value: str | None, maximum: int) -> str | None:
        return value[:maximum] if value is not None else None

    return GroundedClinicalFact(
        category=category,
        display=bounded(record.display, 200),
        status=bounded(record.status, 80),
        effective_at=bounded(record.effective_at, 80),
        value=bounded(record.value, 200),
    )


def build_grounded_generation_request(
    *,
    query: str,
    patient: PatientSummary,
    guidelines: list[Citation],
) -> GroundedGenerationRequest:
    """Build one strict data-only request after retrieval and safety pass."""

    normalized_query = query.casefold()
    forbidden_values = [patient.patient_id]
    if patient.display_name is not None:
        forbidden_values.append(patient.display_name)
    if patient.truncated_categories or any(
        value.casefold() in normalized_query for value in forbidden_values
    ):
        raise ResponseGenerationInputError("grounded generation input is invalid")

    try:
        facts = [
            _clinical_fact(category, record)
            for category, record in _selected_records(query, patient)
        ]
        evidence = [
            GroundedEvidence(rank=index, citation=citation)
            for index, citation in enumerate(guidelines, start=1)
        ]
        return GroundedGenerationRequest(
            question=query,
            patient_context=GroundedPatientContext(facts=facts),
            evidence=evidence,
        )
    except ValidationError:
        raise ResponseGenerationInputError(
            "grounded generation input is invalid"
        ) from None
