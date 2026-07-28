"""Phase 2.1 workflow transition and LangGraph skeleton tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import langsmith as ls
import pytest
from pydantic import ValidationError

from app.domain.audit import AuditEventType
from app.domain.clinical import (
    Citation,
    ClinicalRecordSummary,
    ClinicalSummaryCategory,
    PatientSummary,
)
from app.domain.safety import (
    SafetyDecision,
    SafetyReason,
    SafetyResult,
    SafetySeverity,
)
from app.domain.workflow import (
    GeneratedResponse,
    Intent,
    IntentClassification,
    ResponseDraft,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.tools.fhir import (
    FhirClientError,
    FhirNotFoundError,
    FhirRequestError,
    FhirResponseError,
    FhirTimeoutError,
    FhirUnavailableError,
)
from app.tools.intent import IntentClassificationError, IntentClassifier
from app.tools.patient import PatientSummaryReader
from app.tools.response import (
    ResponseGenerationError,
    ResponseGenerationTimeoutError,
    ResponseGenerator,
)
from app.tools.safety import SafetyPolicy, SafetyPolicyError
from app.workflow.graph import (
    BEGIN_EXECUTION_NODE,
    CLASSIFICATION_FAILURE_CODE,
    CLASSIFY_INTENT_NODE,
    EDUCATIONAL_DISCLAIMER,
    GENERATE_RESPONSE_NODE,
    GUIDELINE_EVIDENCE_UNAVAILABLE_CODE,
    INVALID_PATIENT_SUMMARY_CODE,
    REJECT_UNSUPPORTED_NODE,
    RESPONSE_FAILURE_CODE,
    RESPONSE_TIMEOUT_CODE,
    RETRIEVE_PATIENT_NODE,
    SAFETY_FAILURE_CODE,
    SAFETY_PRECHECK_NODE,
    build_workflow_graph,
    execute_workflow,
    execute_workflow_skeleton,
)
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    InvalidWorkflowTransition,
    append_transitions,
    transition_workflow,
)

WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
CORRELATION_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 7, 28, 9, 1, tzinfo=UTC)


@dataclass(frozen=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class SequentialAuditEventIdFactory:
    def __init__(self) -> None:
        self.next_value = 1

    def new(self) -> UUID:
        event_id = UUID(int=self.next_value)
        self.next_value += 1
        return event_id


class FailingClassifier:
    async def classify(self, query: str) -> IntentClassification:
        raise IntentClassificationError("sensitive classifier failure")


class MalformedClassifier:
    async def classify(self, query: str) -> IntentClassification:
        return cast(
            IntentClassification,
            {"intent": "not-a-supported-intent"},
        )


class StaticPatientSummaryReader:
    def __init__(
        self,
        result: PatientSummary | FhirClientError,
    ) -> None:
        self.result = result
        self.calls = 0

    async def get(self, patient_id: str) -> PatientSummary:
        self.calls += 1
        if isinstance(self.result, FhirClientError):
            raise self.result
        return self.result


class MalformedPatientSummaryReader:
    async def get(self, patient_id: str) -> PatientSummary:
        return cast(
            PatientSummary,
            {
                "patient_id": patient_id,
                "unexpected_raw_field": "sensitive patient payload",
            },
        )


class StaticSafetyPolicy:
    def __init__(
        self,
        result: SafetyResult | SafetyPolicyError,
    ) -> None:
        self.result = result

    async def evaluate(
        self,
        *,
        query: str,
        patient: PatientSummary,
    ) -> SafetyResult:
        if isinstance(self.result, SafetyPolicyError):
            raise self.result
        return self.result


class MalformedSafetyPolicy:
    async def evaluate(
        self,
        *,
        query: str,
        patient: PatientSummary,
    ) -> SafetyResult:
        return cast(
            SafetyResult,
            {
                "decision": "unsafe-provider-value",
                "requires_human_review": False,
                "policy_version": "malformed",
            },
        )


class StaticResponseGenerator:
    def __init__(
        self,
        result: ResponseDraft | ResponseGenerationError,
    ) -> None:
        self.result = result
        self.calls = 0

    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        self.calls += 1
        if isinstance(self.result, ResponseGenerationError):
            raise self.result
        return self.result


class MalformedResponseGenerator:
    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        return cast(
            ResponseDraft,
            {
                "answer": "Unqualified output",
                "citations": ["fabricated-provider-citation"],
                "disclaimer": "Provider-controlled disclaimer",
            },
        )


def complete_patient_summary(
    *,
    patient_id: str = "synthetic-patient-1",
    truncated_categories: list[ClinicalSummaryCategory] | None = None,
) -> PatientSummary:
    return PatientSummary(
        patient_id=patient_id,
        conditions=[
            ClinicalRecordSummary(
                code="example",
                display="Synthetic condition",
                status="active",
            )
        ],
        truncated_categories=truncated_categories or [],
    )


def workflow_runtime(
    classifier: IntentClassifier | None = None,
    *,
    patient_reader: PatientSummaryReader | None = None,
    safety_policy: SafetyPolicy | None = None,
    response_generator: ResponseGenerator | None = None,
) -> WorkflowRuntime:
    return WorkflowRuntime(
        clock=FixedClock(EXECUTED_AT),
        intent_classifier=classifier or DeterministicIntentClassifier(),
        patient_summary_reader=(
            patient_reader or StaticPatientSummaryReader(complete_patient_summary())
        ),
        safety_policy=safety_policy or DeterministicSafetyPolicy(),
        response_generator=response_generator or DeterministicResponseGenerator(),
        audit_event_ids=SequentialAuditEventIdFactory(),
    )


def queued_workflow(
    query: str = "What precautions relate to this patient's conditions?",
) -> WorkflowState:
    return WorkflowState(
        workflow_id=WORKFLOW_ID,
        correlation_id=CORRELATION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        user_query=query,
        patient_id="synthetic-patient-1",
    )


def transition(
    from_status: WorkflowStatus,
    to_status: WorkflowStatus,
    *,
    step: str,
) -> WorkflowTransition:
    return WorkflowTransition(
        from_status=from_status,
        to_status=to_status,
        occurred_at=EXECUTED_AT,
        step=step,
    )


def test_transition_reducer_is_append_only_without_mutating_inputs() -> None:
    current = [
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            step="first",
        )
    ]
    updates = [
        transition(
            WorkflowStatus.RUNNING,
            WorkflowStatus.FAILED,
            step="second",
        )
    ]

    merged = append_transitions(current, updates)

    assert [item.step for item in merged] == ["first", "second"]
    assert [item.step for item in current] == ["first"]
    assert [item.step for item in updates] == ["second"]
    assert merged is not current
    assert merged is not updates


def test_applies_valid_transition_with_monotonic_timestamp() -> None:
    updated, recorded = transition_workflow(
        queued_workflow(),
        WorkflowStatus.RUNNING,
        occurred_at=EXECUTED_AT,
        step=BEGIN_EXECUTION_NODE,
    )

    assert updated.status == WorkflowStatus.RUNNING
    assert updated.updated_at == EXECUTED_AT
    assert updated.failure_code is None
    assert recorded.from_status == WorkflowStatus.QUEUED
    assert recorded.to_status == WorkflowStatus.RUNNING
    assert recorded.step == BEGIN_EXECUTION_NODE


@pytest.mark.parametrize(
    ("initial_status", "target_status"),
    [
        (WorkflowStatus.QUEUED, WorkflowStatus.COMPLETED),
        (WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING),
        (WorkflowStatus.REJECTED, WorkflowStatus.RUNNING),
        (WorkflowStatus.FAILED, WorkflowStatus.RUNNING),
    ],
)
def test_rejects_invalid_and_terminal_transitions(
    initial_status: WorkflowStatus,
    target_status: WorkflowStatus,
) -> None:
    values = queued_workflow().model_dump()
    values["status"] = initial_status
    if initial_status == WorkflowStatus.COMPLETED:
        values["final_response"] = GeneratedResponse(
            answer="Completed educational answer.",
            disclaimer=EDUCATIONAL_DISCLAIMER,
        )
    if initial_status == WorkflowStatus.FAILED:
        values["failure_code"] = "already_failed"
    workflow = WorkflowState.model_validate(values)

    with pytest.raises(InvalidWorkflowTransition, match="not allowed"):
        transition_workflow(
            workflow,
            target_status,
            occurred_at=EXECUTED_AT,
            step="invalid_transition",
        )


def test_rejects_non_monotonic_or_naive_transition_time() -> None:
    with pytest.raises(InvalidWorkflowTransition, match="monotonic"):
        transition_workflow(
            queued_workflow(),
            WorkflowStatus.RUNNING,
            occurred_at=CREATED_AT - timedelta(seconds=1),
            step=BEGIN_EXECUTION_NODE,
        )

    with pytest.raises(InvalidWorkflowTransition, match="fields are invalid"):
        transition_workflow(
            queued_workflow(),
            WorkflowStatus.RUNNING,
            occurred_at=datetime(2026, 7, 28, 9, 1),
            step=BEGIN_EXECUTION_NODE,
        )


@pytest.mark.parametrize(
    ("target_status", "failure_code"),
    [
        (WorkflowStatus.FAILED, None),
        (WorkflowStatus.RUNNING, "unexpected_failure"),
    ],
)
def test_failure_code_matches_failed_transition(
    target_status: WorkflowStatus,
    failure_code: str | None,
) -> None:
    with pytest.raises(InvalidWorkflowTransition, match="failure_code"):
        transition_workflow(
            queued_workflow(),
            target_status,
            occurred_at=EXECUTED_AT,
            step="failure_code_check",
            failure_code=failure_code,
        )


def test_execution_result_rejects_broken_transition_history() -> None:
    failed_values = queued_workflow().model_dump()
    failed_values.update(
        {
            "status": WorkflowStatus.FAILED,
            "updated_at": EXECUTED_AT,
            "failure_code": "expected_failure",
        }
    )
    failed_workflow = WorkflowState.model_validate(failed_values)
    broken_history = [
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            step="first",
        ),
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.FAILED,
            step="broken",
        ),
    ]

    with pytest.raises(ValidationError, match="status chain"):
        WorkflowExecutionResult(
            workflow=failed_workflow,
            transitions=broken_history,
        )


def test_graph_has_only_the_reviewed_response_and_audit_topology() -> None:
    graph = build_workflow_graph().get_graph()

    assert set(graph.nodes) == {
        "__start__",
        BEGIN_EXECUTION_NODE,
        CLASSIFY_INTENT_NODE,
        REJECT_UNSUPPORTED_NODE,
        RETRIEVE_PATIENT_NODE,
        SAFETY_PRECHECK_NODE,
        GENERATE_RESPONSE_NODE,
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", BEGIN_EXECUTION_NODE),
        (BEGIN_EXECUTION_NODE, CLASSIFY_INTENT_NODE),
        (CLASSIFY_INTENT_NODE, RETRIEVE_PATIENT_NODE),
        (CLASSIFY_INTENT_NODE, REJECT_UNSUPPORTED_NODE),
        (CLASSIFY_INTENT_NODE, "__end__"),
        (RETRIEVE_PATIENT_NODE, SAFETY_PRECHECK_NODE),
        (RETRIEVE_PATIENT_NODE, "__end__"),
        (SAFETY_PRECHECK_NODE, GENERATE_RESPONSE_NODE),
        (SAFETY_PRECHECK_NODE, "__end__"),
        (REJECT_UNSUPPORTED_NODE, "__end__"),
        (GENERATE_RESPONSE_NODE, "__end__"),
    }


@pytest.mark.anyio
async def test_supported_intent_completes_with_qualified_response_and_audit() -> None:
    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(),
    )

    assert result.workflow.status == WorkflowStatus.COMPLETED
    assert result.workflow.intent == Intent.CLINICAL_QA
    assert result.workflow.failure_code is None
    assert result.workflow.updated_at == EXECUTED_AT
    assert result.workflow.patient_data == complete_patient_summary()
    assert result.workflow.safety_result is not None
    assert result.workflow.safety_result.decision == SafetyDecision.PASS
    assert [
        (item.from_status, item.to_status, item.step) for item in result.transitions
    ] == [
        (
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            BEGIN_EXECUTION_NODE,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowStatus.COMPLETED,
            GENERATE_RESPONSE_NODE,
        ),
    ]
    assert result.workflow.final_response is not None
    assert result.workflow.final_response.disclaimer == EDUCATIONAL_DISCLAIMER
    assert result.workflow.final_response.citations == []
    assert "No curated guideline evidence" in result.workflow.final_response.answer
    assert [event.event_type for event in result.workflow.audit_log] == [
        AuditEventType.STATUS_CHANGED,
        AuditEventType.TOOL_CALLED,
        AuditEventType.TOOL_CALLED,
        AuditEventType.SAFETY_EVALUATED,
        AuditEventType.RESPONSE_GENERATED,
        AuditEventType.STATUS_CHANGED,
    ]
    assert len({event.event_id for event in result.workflow.audit_log}) == len(
        result.workflow.audit_log
    )
    serialized_audit = str(
        [event.model_dump(mode="json") for event in result.workflow.audit_log]
    )
    assert result.workflow.user_query not in serialized_audit
    assert result.workflow.patient_id not in serialized_audit
    assert "Synthetic condition" not in serialized_audit


@pytest.mark.anyio
async def test_unknown_intent_is_rejected_without_reaching_clinical_path() -> None:
    result = await execute_workflow_skeleton(
        queued_workflow("Please schedule an appointment"),
        runtime=workflow_runtime(),
    )

    assert result.workflow.status == WorkflowStatus.REJECTED
    assert result.workflow.intent == Intent.UNKNOWN
    assert result.workflow.failure_code is None
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        REJECT_UNSUPPORTED_NODE,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (FhirNotFoundError("sensitive"), "patient_not_found"),
        (FhirRequestError("sensitive"), "invalid_patient_id"),
        (FhirTimeoutError("sensitive"), "fhir_timeout"),
        (FhirUnavailableError("sensitive"), "fhir_unavailable"),
        (FhirResponseError("sensitive"), "invalid_fhir_response"),
        (FhirClientError("sensitive"), "fhir_request_failed"),
    ],
)
async def test_maps_patient_retrieval_failures_to_safe_workflow_codes(
    error: FhirClientError,
    expected_code: str,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(patient_reader=StaticPatientSummaryReader(error)),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == expected_code
    assert result.workflow.patient_data is None
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        RETRIEVE_PATIENT_NODE,
    ]
    assert "sensitive" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "patient_reader",
    [
        MalformedPatientSummaryReader(),
        StaticPatientSummaryReader(
            complete_patient_summary(patient_id="different-patient")
        ),
    ],
)
async def test_rejects_malformed_or_mismatched_patient_summary(
    patient_reader: PatientSummaryReader,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(patient_reader=patient_reader),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == INVALID_PATIENT_SUMMARY_CODE
    assert result.workflow.patient_data is None
    assert "sensitive patient payload" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
async def test_urgent_language_pauses_for_future_review() -> None:
    response_generator = StaticResponseGenerator(ResponseDraft(answer="must not run"))
    result = await execute_workflow_skeleton(
        queued_workflow("What precautions apply to chest pain?"),
        runtime=workflow_runtime(response_generator=response_generator),
    )

    assert result.workflow.status == WorkflowStatus.PENDING_REVIEW
    assert result.workflow.requires_human_review is True
    assert result.workflow.safety_result is not None
    assert [reason.code for reason in result.workflow.safety_result.reasons] == [
        "urgent_language"
    ]
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        SAFETY_PRECHECK_NODE,
    ]
    assert response_generator.calls == 0
    assert result.workflow.final_response is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("patient", "expected_reason"),
    [
        (
            PatientSummary(patient_id="synthetic-patient-1"),
            "missing_core_context",
        ),
        (
            complete_patient_summary(
                truncated_categories=["observations"],
            ),
            "patient_context_truncated",
        ),
    ],
)
async def test_sparse_or_truncated_context_pauses_for_review(
    patient: PatientSummary,
    expected_reason: str,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(patient_reader=StaticPatientSummaryReader(patient)),
    )

    assert result.workflow.status == WorkflowStatus.PENDING_REVIEW
    assert result.workflow.safety_result is not None
    assert expected_reason in {
        reason.code for reason in result.workflow.safety_result.reasons
    }


@pytest.mark.anyio
async def test_block_decision_rejects_without_implementing_review_actions() -> None:
    blocked = SafetyResult(
        decision=SafetyDecision.BLOCK,
        requires_human_review=False,
        policy_version="test-policy",
        reasons=[
            SafetyReason(
                code="test_block",
                message="A deterministic test block.",
                severity=SafetySeverity.HIGH,
            )
        ],
    )
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(
            safety_policy=StaticSafetyPolicy(blocked),
        ),
    )

    assert result.workflow.status == WorkflowStatus.REJECTED
    assert result.workflow.safety_result == blocked
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        SAFETY_PRECHECK_NODE,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "safety_policy",
    [
        StaticSafetyPolicy(SafetyPolicyError("sensitive safety failure")),
        MalformedSafetyPolicy(),
    ],
)
async def test_safety_failure_or_malformed_output_fails_safely(
    safety_policy: SafetyPolicy,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(safety_policy=safety_policy),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == SAFETY_FAILURE_CODE
    assert result.workflow.safety_result is None
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        SAFETY_PRECHECK_NODE,
    ]
    assert "sensitive" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "classifier",
    [FailingClassifier(), MalformedClassifier()],
)
async def test_classifier_failure_or_malformed_output_fails_safely(
    classifier: IntentClassifier,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(classifier),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.intent == Intent.UNKNOWN
    assert result.workflow.failure_code == CLASSIFICATION_FAILURE_CODE
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        CLASSIFY_INTENT_NODE,
    ]
    assert "sensitive" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response_generator", "expected_code"),
    [
        (
            StaticResponseGenerator(
                ResponseGenerationTimeoutError("sensitive timeout")
            ),
            RESPONSE_TIMEOUT_CODE,
        ),
        (
            StaticResponseGenerator(ResponseGenerationError("sensitive failure")),
            RESPONSE_FAILURE_CODE,
        ),
        (MalformedResponseGenerator(), RESPONSE_FAILURE_CODE),
    ],
)
async def test_response_failure_timeout_or_untrusted_output_fails_safely(
    response_generator: ResponseGenerator,
    expected_code: str,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(response_generator=response_generator),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == expected_code
    assert result.workflow.final_response is None
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        GENERATE_RESPONSE_NODE,
    ]
    serialized = str(result.model_dump(mode="json"))
    assert "sensitive" not in serialized
    assert "fabricated-provider-citation" not in serialized
    assert "Provider-controlled disclaimer" not in serialized


@pytest.mark.anyio
async def test_phase_3_guideline_context_is_not_accepted_early() -> None:
    values = queued_workflow().model_dump()
    values["retrieved_guidelines"] = [
        Citation(
            document_id="future-guideline",
            chunk_id="future-chunk",
            title="Future guideline",
            publisher="Future publisher",
            source_url="https://example.test/future",
        )
    ]
    response_generator = StaticResponseGenerator(ResponseDraft(answer="must not run"))

    result = await execute_workflow_skeleton(
        WorkflowState.model_validate(values),
        runtime=workflow_runtime(response_generator=response_generator),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == GUIDELINE_EVIDENCE_UNAVAILABLE_CODE
    assert result.workflow.final_response is None
    assert response_generator.calls == 0


@pytest.mark.anyio
async def test_workflow_replay_is_deterministic() -> None:
    first = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(),
    )
    second = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(),
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.anyio
async def test_skeleton_explicitly_disables_external_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracing_values: list[bool | None] = []

    @contextmanager
    def tracing_context(*, enabled: bool | None = None) -> Iterator[None]:
        tracing_values.append(enabled)
        yield

    monkeypatch.setattr(
        ls,
        "tracing_context",
        tracing_context,
    )

    await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(),
    )

    assert tracing_values == [False]
