"""Versioned deterministic safety pre-check tests."""

import pytest

from app.domain.clinical import ClinicalRecordSummary, PatientSummary
from app.domain.safety import SafetyDecision, SafetySeverity
from app.services.deterministic_safety import (
    INITIAL_SAFETY_POLICY_VERSION,
    SAFETY_PRECHECK_POLICY_VERSION,
    SAFETY_RULES,
    DeterministicSafetyPolicy,
)


def patient_with_core_context(
    *,
    truncated: bool = False,
) -> PatientSummary:
    return PatientSummary(
        patient_id="synthetic-patient-1",
        conditions=[
            ClinicalRecordSummary(
                code="example",
                display="Synthetic condition",
            )
        ],
        truncated_categories=["observations"] if truncated else [],
    )


@pytest.mark.anyio
async def test_complete_context_passes_initial_policy() -> None:
    result = await DeterministicSafetyPolicy().evaluate(
        query="What precautions relate to these conditions?",
        patient=patient_with_core_context(),
    )

    assert result.decision == SafetyDecision.PASS
    assert result.requires_human_review is False
    assert result.policy_version == INITIAL_SAFETY_POLICY_VERSION
    assert result.policy_version == SAFETY_PRECHECK_POLICY_VERSION
    assert result.reasons == []


def test_safety_rule_catalog_has_stable_versioned_metadata() -> None:
    assert set(SAFETY_RULES) == {
        "urgent_language",
        "medication_allergy_conflict",
        "missing_core_context",
        "patient_context_truncated",
    }
    assert SAFETY_RULES["medication_allergy_conflict"].severity == SafetySeverity.HIGH
    assert SAFETY_RULES["missing_core_context"].evidence_references == (
        "patient:conditions",
        "patient:allergies",
        "patient:medications",
        "patient:observations",
    )


@pytest.mark.anyio
async def test_urgent_language_requires_review_without_echoing_query() -> None:
    query = "I have chest pain with private-marker-123"
    result = await DeterministicSafetyPolicy().evaluate(
        query=query,
        patient=patient_with_core_context(),
    )

    assert result.decision == SafetyDecision.REVIEW
    assert result.requires_human_review is True
    assert [(reason.code, reason.severity) for reason in result.reasons] == [
        ("urgent_language", SafetySeverity.HIGH)
    ]
    assert "private-marker-123" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
async def test_missing_core_context_requires_review() -> None:
    result = await DeterministicSafetyPolicy().evaluate(
        query="What precautions relate to these conditions?",
        patient=PatientSummary(patient_id="synthetic-patient-1"),
    )

    assert result.decision == SafetyDecision.REVIEW
    assert [reason.code for reason in result.reasons] == ["missing_core_context"]


@pytest.mark.anyio
async def test_medication_allergy_conflict_requires_review_without_names() -> None:
    result = await DeterministicSafetyPolicy().evaluate(
        query="What precautions relate to this medication?",
        patient=PatientSummary(
            patient_id="synthetic-patient-1",
            allergies=[
                ClinicalRecordSummary(
                    display="private-marker allergy",
                    code="private-marker",
                )
            ],
            medications=[
                ClinicalRecordSummary(
                    display="private-marker tablet",
                    code="private-marker",
                )
            ],
        ),
    )

    assert result.decision == SafetyDecision.REVIEW
    assert [(reason.code, reason.severity) for reason in result.reasons] == [
        ("medication_allergy_conflict", SafetySeverity.HIGH)
    ]
    assert result.reasons[0].evidence_references == [
        "patient:allergies",
        "patient:medications",
    ]
    assert "private-marker" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
async def test_medication_allergy_generic_terms_do_not_conflict() -> None:
    result = await DeterministicSafetyPolicy().evaluate(
        query="What precautions relate to this medication?",
        patient=PatientSummary(
            patient_id="synthetic-patient-1",
            allergies=[ClinicalRecordSummary(display="Unspecified drug allergy")],
            medications=[ClinicalRecordSummary(display="Daily oral medication")],
        ),
    )

    assert result.decision == SafetyDecision.PASS
    assert result.reasons == []


@pytest.mark.anyio
async def test_truncated_context_requires_review_with_category_reference() -> None:
    result = await DeterministicSafetyPolicy().evaluate(
        query="What precautions relate to these conditions?",
        patient=patient_with_core_context(truncated=True),
    )

    assert result.decision == SafetyDecision.REVIEW
    assert result.reasons[0].code == "patient_context_truncated"
    assert result.reasons[0].evidence_references == ["patient:observations"]


@pytest.mark.anyio
async def test_multiple_rules_have_stable_order_and_replay() -> None:
    policy = DeterministicSafetyPolicy()
    patient = PatientSummary(
        patient_id="synthetic-patient-1",
        truncated_categories=["conditions"],
    )

    first = await policy.evaluate(
        query="Difficulty   breathing",
        patient=patient,
    )
    second = await policy.evaluate(
        query="Difficulty   breathing",
        patient=patient,
    )

    assert [reason.code for reason in first.reasons] == [
        "urgent_language",
        "missing_core_context",
        "patient_context_truncated",
    ]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
