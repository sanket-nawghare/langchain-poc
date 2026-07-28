"""Bounded workflow request and deterministic intent classification tests."""

import pytest
from pydantic import ValidationError

from app.domain.workflow import Intent, IntentClassification, WorkflowRunRequest
from app.services.deterministic_intent import DeterministicIntentClassifier


def test_workflow_request_trims_bounded_input() -> None:
    request = WorkflowRunRequest(
        patient_id="  synthetic-patient-1  ",
        query="  What precautions relate to this patient's conditions?  ",
    )

    assert request.patient_id == "synthetic-patient-1"
    assert request.query == "What precautions relate to this patient's conditions?"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "x" * 2001,
    ],
)
def test_workflow_request_rejects_empty_or_oversized_query(query: str) -> None:
    with pytest.raises(ValidationError):
        WorkflowRunRequest(patient_id="synthetic-patient-1", query=query)


@pytest.mark.parametrize(
    "patient_id",
    [
        "unsafe/id",
        "not_a_fhir_id",
        "x" * 65,
    ],
)
def test_workflow_request_rejects_invalid_fhir_patient_id(
    patient_id: str,
) -> None:
    with pytest.raises(ValidationError):
        WorkflowRunRequest(patient_id=patient_id, query="A clinical question")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "What precautions relate to this patient's conditions?",
            Intent.CLINICAL_QA,
        ),
        ("Please schedule an appointment", Intent.UNKNOWN),
        ("Schedule an appointment about my medication", Intent.UNKNOWN),
        ("Can you help me with this?", Intent.UNKNOWN),
    ],
)
async def test_deterministic_classifier_uses_conservative_fallback(
    query: str,
    expected: Intent,
) -> None:
    result = await DeterministicIntentClassifier().classify(query)

    assert result == IntentClassification(intent=expected)


def test_intent_classification_rejects_unknown_provider_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected_provider_field"):
        IntentClassification.model_validate(
            {
                "intent": "clinical_qa",
                "unexpected_provider_field": "must not cross boundary",
            }
        )
