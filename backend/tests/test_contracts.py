"""Durable domain-contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain import (
    ApiError,
    Citation,
    ErrorDetail,
    Intent,
    SafetyDecision,
    SafetyReason,
    SafetyResult,
    SafetySeverity,
    WorkflowState,
)


def citation() -> Citation:
    return Citation(
        document_id="guideline-1",
        chunk_id="chunk-1",
        title="Synthetic test guideline",
        publisher="Example publisher",
        source_url="https://example.test/guideline",
        page=4,
    )


def test_workflow_state_serializes_to_provider_neutral_json() -> None:
    now = datetime.now(UTC)
    workflow_id = uuid4()
    correlation_id = uuid4()
    safety_result = SafetyResult(
        decision=SafetyDecision.PASS,
        requires_human_review=False,
        policy_version="safety-v1",
    )
    state = WorkflowState(
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        created_at=now,
        updated_at=now,
        user_query="What guidance is relevant?",
        intent=Intent.CLINICAL_QA,
        patient_id="synthetic-patient-001",
        retrieved_guidelines=[citation()],
        safety_result=safety_result,
        requires_human_review=False,
    )

    serialized = state.model_dump(mode="json")

    assert serialized["workflow_id"] == str(workflow_id)
    assert serialized["intent"] == "clinical_qa"
    assert (
        serialized["retrieved_guidelines"][0]["source_url"]
        == "https://example.test/guideline"
    )


def test_workflow_state_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        WorkflowState(
            workflow_id=uuid4(),
            correlation_id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(UTC),
            user_query="Question",
            patient_id="synthetic-patient-001",
        )


def test_workflow_state_requires_chronology_and_failed_status_code() -> None:
    now = datetime.now(UTC)
    base_values = {
        "workflow_id": uuid4(),
        "correlation_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "user_query": "Question",
        "patient_id": "synthetic-patient-001",
    }

    with pytest.raises(ValidationError, match="must not precede"):
        WorkflowState.model_validate(
            {
                **base_values,
                "updated_at": now - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="failure_code"):
        WorkflowState.model_validate({**base_values, "status": "failed"})
    with pytest.raises(ValidationError, match="failure_code"):
        WorkflowState.model_validate({**base_values, "failure_code": "unexpected"})


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        # The invalid keyword is intentional to exercise runtime validation.
        Citation(  # type: ignore[call-arg]
            document_id="guideline-1",
            chunk_id="chunk-1",
            title="Synthetic test guideline",
            publisher="Example publisher",
            source_url="https://example.test/guideline",
            unexpected="provider-specific value",
        )


def test_safety_result_rejects_contradictory_review_flag() -> None:
    with pytest.raises(
        ValidationError,
        match="requires_human_review",
    ):
        SafetyResult(
            decision=SafetyDecision.REVIEW,
            requires_human_review=False,
            policy_version="safety-v1",
            reasons=[
                SafetyReason(
                    code="review-required",
                    message="A reviewer must inspect this test case.",
                    severity=SafetySeverity.WARNING,
                )
            ],
        )


def test_api_error_contains_safe_stable_fields() -> None:
    request_id = uuid4()
    response = ApiError(
        request_id=request_id,
        error=ErrorDetail(
            code="invalid_request",
            message="The request could not be validated.",
            field="patient_id",
        ),
    )

    assert response.model_dump(mode="json") == {
        "request_id": str(request_id),
        "error": {
            "code": "invalid_request",
            "message": "The request could not be validated.",
            "field": "patient_id",
        },
    }
