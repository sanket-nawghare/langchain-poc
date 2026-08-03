"""Durable domain-contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain import (
    ActorType,
    ApiError,
    AuditEvent,
    AuditEventType,
    Citation,
    ErrorDetail,
    EvidenceAssessment,
    GeneratedResponse,
    GuidelineEvidenceSummary,
    Intent,
    ResponseDraft,
    SafetyDecision,
    SafetyReason,
    SafetyResult,
    SafetySeverity,
    WorkflowState,
    WorkflowStatus,
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
        guideline_evidence=GuidelineEvidenceSummary(
            assessment=EvidenceAssessment.SUFFICIENT,
            policy_version="retrieval-v1",
            query_fingerprint="0" * 64,
            match_count=1,
            document_ids=["guideline-1"],
            chunk_ids=["chunk-1"],
        ),
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


def test_workflow_state_rejects_citations_without_matching_evidence() -> None:
    now = datetime.now(UTC)
    base_values = {
        "workflow_id": uuid4(),
        "correlation_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "user_query": "Question",
        "patient_id": "synthetic-patient-001",
    }

    with pytest.raises(ValidationError, match="evidence summary"):
        WorkflowState.model_validate(
            {**base_values, "retrieved_guidelines": [citation()]}
        )
    with pytest.raises(ValidationError, match="chunk IDs"):
        WorkflowState.model_validate(
            {
                **base_values,
                "guideline_evidence": {
                    "assessment": "sufficient",
                    "policy_version": "retrieval-v1",
                    "query_fingerprint": "0" * 64,
                    "match_count": 1,
                    "document_ids": ["guideline-1"],
                    "chunk_ids": ["different-chunk"],
                },
                "retrieved_guidelines": [citation()],
            }
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


def test_response_draft_is_bounded_and_rejects_provider_qualifications() -> None:
    with pytest.raises(ValidationError, match="at most 4000"):
        ResponseDraft(answer="x" * 4001)

    with pytest.raises(ValidationError, match="citations"):
        ResponseDraft.model_validate(
            {
                "answer": "Draft answer",
                "citations": ["provider-controlled"],
            }
        )


def test_final_response_exists_only_on_completed_workflow() -> None:
    now = datetime.now(UTC)
    values = {
        "workflow_id": uuid4(),
        "correlation_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "user_query": "Question",
        "patient_id": "synthetic-patient-001",
    }
    response = GeneratedResponse(
        answer="Bounded educational answer.",
        citations=[citation()],
        disclaimer="Educational demonstration only.",
    )
    evidence = GuidelineEvidenceSummary(
        assessment=EvidenceAssessment.SUFFICIENT,
        policy_version="retrieval-v1",
        query_fingerprint="0" * 64,
        match_count=1,
        document_ids=["guideline-1"],
        chunk_ids=["chunk-1"],
    )

    with pytest.raises(ValidationError, match="final_response"):
        WorkflowState.model_validate({**values, "status": WorkflowStatus.COMPLETED})
    with pytest.raises(ValidationError, match="final_response"):
        WorkflowState.model_validate({**values, "final_response": response})

    completed = WorkflowState.model_validate(
        {
            **values,
            "status": WorkflowStatus.COMPLETED,
            "guideline_evidence": evidence,
            "retrieved_guidelines": [citation()],
            "final_response": response,
        }
    )
    assert completed.final_response == response


@pytest.mark.parametrize("invalid_audit", ["mismatched_workflow", "duplicate_id"])
def test_workflow_rejects_mismatched_or_duplicate_audit_events(
    invalid_audit: str,
) -> None:
    now = datetime.now(UTC)
    workflow_id = uuid4()
    correlation_id = uuid4()
    event_id = uuid4()
    event = AuditEvent(
        event_id=event_id,
        workflow_id=(
            uuid4() if invalid_audit == "mismatched_workflow" else workflow_id
        ),
        correlation_id=correlation_id,
        event_type=AuditEventType.STATUS_CHANGED,
        occurred_at=now,
        actor_type=ActorType.SYSTEM,
        details={"step": "test"},
    )
    audit_log = [event, event] if invalid_audit == "duplicate_id" else [event]

    with pytest.raises(ValidationError, match="audit"):
        WorkflowState(
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
            user_query="Question",
            patient_id="synthetic-patient-001",
            audit_log=audit_log,
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
