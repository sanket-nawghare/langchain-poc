"""Phase 2.1 workflow transition and LangGraph skeleton tests."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
from app.domain.guidelines import (
    EvidenceAssessment,
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineEvidenceSummary,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineRetrievalMatch,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
    GuidelineSource,
    GuidelineUsePermission,
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
from app.rag.retrieval import (
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
    GuidelineRetriever,
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
    CLASSIFICATION_TIMEOUT_CODE,
    CLASSIFY_INTENT_NODE,
    EDUCATIONAL_DISCLAIMER,
    GENERATE_RESPONSE_NODE,
    GUIDELINE_RETRIEVAL_TIMEOUT_CODE,
    GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE,
    INVALID_GUIDELINE_EVIDENCE_CODE,
    INVALID_PATIENT_SUMMARY_CODE,
    REJECT_UNSUPPORTED_NODE,
    RESPONSE_FAILURE_CODE,
    RESPONSE_TIMEOUT_CODE,
    RETRIEVE_GUIDELINES_NODE,
    RETRIEVE_PATIENT_NODE,
    SAFETY_FAILURE_CODE,
    SAFETY_PRECHECK_NODE,
    build_workflow_graph,
    execute_workflow,
    execute_workflow_skeleton,
)
from app.workflow.runtime import WorkflowExecutionPolicy, WorkflowRuntime
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


class HangingClassifier:
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, query: str) -> IntentClassification:
        self.calls += 1
        await asyncio.sleep(0.05)
        return IntentClassification(intent=Intent.CLINICAL_QA)


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


class UnexpectedResponseGenerator:
    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        raise RuntimeError("sensitive unexpected provider failure")


class FlakyResponseGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        self.calls += 1
        if self.calls == 1:
            raise ResponseGenerationError("transient sensitive failure")
        return ResponseDraft(answer="Recovered bounded educational draft.")


class StubGuidelineRetriever:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.requests: list[GuidelineRetrievalRequest] = []

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return cast(GuidelineRetrievalResult, result)

    async def close(self) -> None:
        return None


class HangingGuidelineRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        self.calls += 1
        await asyncio.sleep(0.05)
        return guideline_result(EvidenceAssessment.SUFFICIENT)

    async def close(self) -> None:
        return None


def guideline_match(rank: int) -> GuidelineRetrievalMatch:
    source = GuidelineSource(
        document_id="who-synthetic-guideline",
        title="Reviewed synthetic guideline",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://example.test/reviewed-guideline",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2026, 1, 1),
        version="2026-v1",
        accessed_at=date(2026, 7, 1),
        license_name="Reviewed test permission",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 7, 1),
        license_review_note="Test-only reviewed source metadata.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256="1" * 64,
        supported_topics=["synthetic condition"],
    )
    chunk = GuidelineChunk(
        chunk_id=f"who-synthetic-guideline.{rank - 1}",
        document_id=source.document_id,
        text=f"Reviewed bounded evidence chunk {rank}.",
        content_sha256=f"{rank + 1}" * 64,
        sequence=rank - 1,
        page=rank,
    )
    return GuidelineRetrievalMatch(
        source=source,
        chunk=chunk,
        citation=Citation(
            document_id=source.document_id,
            chunk_id=chunk.chunk_id,
            title=source.title,
            publisher=source.publisher.value,
            source_url=source.canonical_url,
            page=chunk.page,
            excerpt=f"Bounded evidence excerpt {rank}.",
        ),
        relevance_score=0.9,
        rank=rank,
    )


def guideline_result(
    assessment: EvidenceAssessment,
) -> GuidelineRetrievalResult:
    match_count = {
        EvidenceAssessment.INSUFFICIENT: 0,
        EvidenceAssessment.SUFFICIENT: 1,
        EvidenceAssessment.CONFLICTING: 2,
    }[assessment]
    return GuidelineRetrievalResult(
        assessment=assessment,
        policy_version="retrieval-v1",
        query_fingerprint="0" * 64,
        matches=[guideline_match(rank) for rank in range(1, match_count + 1)],
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
    guideline_retriever: GuidelineRetriever | None = None,
    without_guideline_retriever: bool = False,
    execution_policy: WorkflowExecutionPolicy | None = None,
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
        guideline_retriever=(
            None
            if without_guideline_retriever
            else guideline_retriever
            or StubGuidelineRetriever(guideline_result(EvidenceAssessment.SUFFICIENT))
        ),
        execution_policy=execution_policy or WorkflowExecutionPolicy(),
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
        retrieval = guideline_result(EvidenceAssessment.SUFFICIENT)
        citations = [match.citation for match in retrieval.matches]
        values["guideline_evidence"] = GuidelineEvidenceSummary.from_retrieval_result(
            retrieval
        )
        values["retrieved_guidelines"] = citations
        values["final_response"] = GeneratedResponse(
            answer="Completed educational answer.",
            citations=citations,
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
        RETRIEVE_GUIDELINES_NODE,
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
        (RETRIEVE_PATIENT_NODE, RETRIEVE_GUIDELINES_NODE),
        (RETRIEVE_PATIENT_NODE, "__end__"),
        (RETRIEVE_GUIDELINES_NODE, SAFETY_PRECHECK_NODE),
        (RETRIEVE_GUIDELINES_NODE, "__end__"),
        (SAFETY_PRECHECK_NODE, GENERATE_RESPONSE_NODE),
        (SAFETY_PRECHECK_NODE, "__end__"),
        (REJECT_UNSUPPORTED_NODE, "__end__"),
        (GENERATE_RESPONSE_NODE, "__end__"),
    }


@pytest.mark.anyio
async def test_sufficient_guideline_evidence_is_projected_and_audited_safely() -> None:
    retriever = StubGuidelineRetriever(guideline_result(EvidenceAssessment.SUFFICIENT))

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(guideline_retriever=retriever),
    )

    assert len(retriever.requests) == 1
    request = retriever.requests[0]
    assert request.clinical_query == queued_workflow().user_query
    assert request.as_of == EXECUTED_AT.date()
    assert "patient" not in request.model_dump()
    assert result.workflow.guideline_evidence is not None
    assert (
        result.workflow.guideline_evidence.assessment is EvidenceAssessment.SUFFICIENT
    )
    assert result.workflow.guideline_evidence.match_count == 1
    assert len(result.workflow.retrieved_guidelines) == 1
    assert result.workflow.status is WorkflowStatus.COMPLETED
    assert result.workflow.failure_code is None
    assert result.workflow.final_response is not None
    assert result.workflow.final_response.citations == (
        result.workflow.retrieved_guidelines
    )
    retrieval_audit = next(
        event
        for event in result.workflow.audit_log
        if event.details.get("tool") == "guideline_retriever"
    )
    assert retrieval_audit.details == {
        "tool": "guideline_retriever",
        "outcome": "success",
        "assessment": "sufficient",
        "policy_version": "retrieval-v1",
        "match_count": 1,
        "document_ids": "who-synthetic-guideline",
        "chunk_ids": "who-synthetic-guideline.0",
    }
    serialized_audit = str(retrieval_audit.model_dump(mode="json"))
    assert queued_workflow().user_query not in serialized_audit
    assert "Reviewed bounded evidence" not in serialized_audit
    assert "Bounded evidence excerpt" not in serialized_audit
    assert "example.test" not in serialized_audit


@pytest.mark.anyio
@pytest.mark.parametrize(
    "assessment",
    [EvidenceAssessment.INSUFFICIENT, EvidenceAssessment.CONFLICTING],
)
async def test_unsafe_evidence_outcomes_pause_before_safety_and_generation(
    assessment: EvidenceAssessment,
) -> None:
    response_generator = StaticResponseGenerator(ResponseDraft(answer="must not run"))

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(
            guideline_retriever=StubGuidelineRetriever(guideline_result(assessment)),
            response_generator=response_generator,
        ),
    )

    assert result.workflow.status is WorkflowStatus.PENDING_REVIEW
    assert result.workflow.requires_human_review is True
    assert result.workflow.guideline_evidence is not None
    assert result.workflow.guideline_evidence.assessment is assessment
    assert result.workflow.safety_result is None
    assert result.workflow.final_response is None
    assert response_generator.calls == 0
    assert result.transitions[-1].step == RETRIEVE_GUIDELINES_NODE


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider_result", "expected_code"),
    [
        (
            GuidelineRetrievalTimeoutError("sensitive timeout"),
            GUIDELINE_RETRIEVAL_TIMEOUT_CODE,
        ),
        (
            GuidelineRetrievalUnavailableError("sensitive unavailable"),
            GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE,
        ),
        (
            GuidelineRetrievalResponseError("sensitive malformed"),
            INVALID_GUIDELINE_EVIDENCE_CODE,
        ),
        (
            {"assessment": "sufficient", "provider_payload": "sensitive"},
            INVALID_GUIDELINE_EVIDENCE_CODE,
        ),
        (RuntimeError("sensitive unexpected failure"), INVALID_GUIDELINE_EVIDENCE_CODE),
    ],
)
async def test_guideline_retrieval_failures_map_to_safe_codes(
    provider_result: object,
    expected_code: str,
) -> None:
    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(
            guideline_retriever=StubGuidelineRetriever(provider_result),
            execution_policy=WorkflowExecutionPolicy(max_retries=0),
        ),
    )

    assert result.workflow.status is WorkflowStatus.FAILED
    assert result.workflow.failure_code == expected_code
    assert result.workflow.guideline_evidence is None
    assert result.transitions[-1].step == RETRIEVE_GUIDELINES_NODE
    serialized = str(result.model_dump(mode="json"))
    assert "sensitive" not in serialized
    assert "provider_payload" not in serialized


@pytest.mark.anyio
async def test_guideline_retrieval_retries_typed_unavailability() -> None:
    retriever = StubGuidelineRetriever(
        GuidelineRetrievalUnavailableError("transient sensitive failure"),
        guideline_result(EvidenceAssessment.INSUFFICIENT),
    )

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(guideline_retriever=retriever),
    )

    assert len(retriever.requests) == 2
    assert result.workflow.status is WorkflowStatus.PENDING_REVIEW
    assert result.workflow.failure_code is None


@pytest.mark.anyio
async def test_guideline_retrieval_enforces_node_timeout() -> None:
    retriever = HangingGuidelineRetriever()

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(
            guideline_retriever=retriever,
            execution_policy=WorkflowExecutionPolicy(
                timeout_seconds=0.001,
                max_retries=1,
            ),
        ),
    )

    assert retriever.calls == 2
    assert result.workflow.status is WorkflowStatus.FAILED
    assert result.workflow.failure_code == GUIDELINE_RETRIEVAL_TIMEOUT_CODE


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
    assert result.workflow.final_response.citations == (
        result.workflow.retrieved_guidelines
    )
    assert len(result.workflow.final_response.citations) == 1
    assert "1 curated guideline reference(s)" in result.workflow.final_response.answer
    assert [event.event_type for event in result.workflow.audit_log] == [
        AuditEventType.STATUS_CHANGED,
        AuditEventType.TOOL_CALLED,
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
        (UnexpectedResponseGenerator(), RESPONSE_FAILURE_CODE),
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
async def test_missing_guideline_retriever_fails_before_generation() -> None:
    response_generator = StaticResponseGenerator(ResponseDraft(answer="must not run"))

    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(
            response_generator=response_generator,
            without_guideline_retriever=True,
        ),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE
    assert result.workflow.final_response is None
    assert response_generator.calls == 0


@pytest.mark.anyio
async def test_retryable_response_failure_recovers_within_bound() -> None:
    response_generator = FlakyResponseGenerator()

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(
            response_generator=response_generator,
            execution_policy=WorkflowExecutionPolicy(
                timeout_seconds=1,
                max_retries=1,
            ),
        ),
    )

    assert result.workflow.status == WorkflowStatus.COMPLETED
    assert response_generator.calls == 2
    assert result.workflow.final_response is not None
    assert result.workflow.final_response.answer == (
        "Recovered bounded educational draft."
    )


@pytest.mark.anyio
async def test_node_timeout_retries_then_fails_with_stable_code() -> None:
    classifier = HangingClassifier()

    result = await execute_workflow(
        queued_workflow(),
        runtime=workflow_runtime(
            classifier,
            execution_policy=WorkflowExecutionPolicy(
                timeout_seconds=0.001,
                max_retries=1,
            ),
        ),
    )

    assert classifier.calls == 2
    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.failure_code == CLASSIFICATION_TIMEOUT_CODE
    assert result.workflow.patient_data is None


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
