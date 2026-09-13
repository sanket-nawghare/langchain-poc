"""Typed workflow state and response contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from app.domain.audit import AuditEvent
from app.domain.base import (
    ContractModel,
    CorrelationId,
    NonEmptyString,
    PatientId,
    TraceId,
    UtcTimestamp,
    WorkflowId,
    WorkflowQuery,
)
from app.domain.clinical import Citation, PatientSummary
from app.domain.guidelines import EvidenceAssessment, GuidelineEvidenceSummary
from app.domain.safety import SafetyResult

MAX_RESPONSE_ANSWER_LENGTH = 4000
MAX_RESPONSE_DISCLAIMER_LENGTH = 500


class Intent(StrEnum):
    """Supported and safely handled request intents."""

    CLINICAL_QA = "clinical_qa"
    UNKNOWN = "unknown"


class WorkflowRunRequest(ContractModel):
    """Bounded untrusted input accepted before graph execution."""

    patient_id: PatientId
    query: WorkflowQuery


class IntentClassification(ContractModel):
    """Structured provider-neutral output from an intent classifier."""

    intent: Intent


class ResponseDraft(ContractModel):
    """Bounded answer text returned by a provider-neutral generator."""

    answer: str = Field(min_length=1, max_length=MAX_RESPONSE_ANSWER_LENGTH)


class ReviewActionType(StrEnum):
    """Reviewer decisions supported by the human-review queue."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ReviewActionRequest(ContractModel):
    """Attributable optimistic-concurrency review action."""

    action: ReviewActionType
    reviewer_id: NonEmptyString = Field(max_length=128)
    rationale: NonEmptyString = Field(max_length=1000)
    review_version: int = Field(ge=0)


class ReviewRecord(ContractModel):
    """Persisted redacted record of one accepted review action."""

    action: ReviewActionType
    reviewer_id: NonEmptyString = Field(max_length=128)
    rationale: NonEmptyString = Field(max_length=1000)
    policy_version: NonEmptyString
    reviewed_at: UtcTimestamp
    review_version: int = Field(ge=1)


class WorkflowStatus(StrEnum):
    """Persistable workflow lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class GeneratedResponse(ContractModel):
    """Qualified final output returned by the workflow."""

    answer: str = Field(min_length=1, max_length=MAX_RESPONSE_ANSWER_LENGTH)
    citations: list[Citation] = Field(default_factory=list)
    disclaimer: str = Field(
        min_length=1,
        max_length=MAX_RESPONSE_DISCLAIMER_LENGTH,
    )


class WorkflowTransition(ContractModel):
    """One safe, inspectable workflow status change."""

    from_status: WorkflowStatus
    to_status: WorkflowStatus
    occurred_at: UtcTimestamp
    step: NonEmptyString


class WorkflowState(ContractModel):
    """Provider-neutral state exchanged by future LangGraph nodes."""

    workflow_id: WorkflowId
    correlation_id: CorrelationId
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    status: WorkflowStatus = WorkflowStatus.QUEUED
    user_query: WorkflowQuery
    intent: Intent = Intent.UNKNOWN
    patient_id: PatientId
    patient_data: PatientSummary | None = None
    guideline_evidence: GuidelineEvidenceSummary | None = None
    retrieved_guidelines: list[Citation] = Field(default_factory=list)
    safety_result: SafetyResult | None = None
    response_draft: ResponseDraft | None = None
    post_generation_safety_result: SafetyResult | None = None
    requires_human_review: bool | None = None
    final_response: GeneratedResponse | None = None
    audit_log: list[AuditEvent] = Field(default_factory=list)
    failure_code: NonEmptyString | None = None

    @model_validator(mode="after")
    def review_flag_matches_safety_result(self) -> "WorkflowState":
        """Keep the routing flag consistent with a completed safety result."""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (self.status == WorkflowStatus.FAILED) != (self.failure_code is not None):
            raise ValueError("failure_code must be set only for a failed workflow")
        if (self.status == WorkflowStatus.COMPLETED) != (
            self.final_response is not None
        ):
            raise ValueError("final_response must be set only for a completed workflow")
        event_ids = set()
        for event in self.audit_log:
            if (
                event.workflow_id != self.workflow_id
                or event.correlation_id != self.correlation_id
            ):
                raise ValueError("audit events must match workflow identifiers")
            if event.event_id in event_ids:
                raise ValueError("audit event IDs must be unique within a workflow")
            event_ids.add(event.event_id)
        if self.guideline_evidence is None:
            if self.retrieved_guidelines:
                raise ValueError(
                    "retrieved guidelines require a guideline evidence summary"
                )
        else:
            evidence = self.guideline_evidence
            citations = self.retrieved_guidelines
            if evidence.match_count != len(citations):
                raise ValueError("guideline evidence must match citation count")
            if evidence.chunk_ids != [citation.chunk_id for citation in citations]:
                raise ValueError("guideline evidence chunk IDs must match citations")
            if set(evidence.document_ids) != {
                citation.document_id for citation in citations
            }:
                raise ValueError("guideline evidence document IDs must match citations")
            if evidence.assessment is EvidenceAssessment.INSUFFICIENT and citations:
                raise ValueError("insufficient evidence must not include citations")
        if self.final_response is not None:
            if (
                self.guideline_evidence is None
                or self.guideline_evidence.assessment
                is not EvidenceAssessment.SUFFICIENT
                or not self.retrieved_guidelines
            ):
                raise ValueError("completed response requires sufficient evidence")
            if self.final_response.citations != self.retrieved_guidelines:
                raise ValueError(
                    "final response citations must match workflow evidence"
                )
        if self.safety_result is None:
            if self.post_generation_safety_result is not None:
                raise ValueError(
                    "post-generation safety requires pre-generation safety"
                )
            return self
        if (
            self.post_generation_safety_result is not None
            and self.response_draft is None
        ):
            raise ValueError("post-generation safety requires a response draft")
        expected_review = self.safety_result.requires_human_review or (
            self.post_generation_safety_result.requires_human_review
            if self.post_generation_safety_result is not None
            else False
        )
        if self.requires_human_review != expected_review:
            raise ValueError("requires_human_review must match safety routing")
        return self


class WorkflowExecutionResult(ContractModel):
    """Validated provider-neutral output from one graph execution."""

    workflow: WorkflowState
    transitions: list[WorkflowTransition] = Field(min_length=1)

    @model_validator(mode="after")
    def transitions_form_a_monotonic_chain(self) -> "WorkflowExecutionResult":
        """Reject broken histories or a final transition that disagrees with state."""

        previous_status = self.transitions[0].from_status
        previous_time = self.workflow.created_at
        for transition in self.transitions:
            if transition.from_status != previous_status:
                raise ValueError("workflow transitions must form a status chain")
            if transition.occurred_at < previous_time:
                raise ValueError("workflow transition timestamps must be monotonic")
            previous_status = transition.to_status
            previous_time = transition.occurred_at
        if previous_status != self.workflow.status:
            raise ValueError("final transition must match workflow status")
        if previous_time != self.workflow.updated_at:
            raise ValueError("final transition must match workflow updated_at")
        return self


class WorkflowRunSnapshot(ContractModel):
    """Redacted persistable and inspectable workflow-run checkpoint."""

    workflow_id: WorkflowId
    correlation_id: CorrelationId
    trace_id: TraceId
    status: WorkflowStatus
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    requires_human_review: bool | None = None
    guideline_evidence: GuidelineEvidenceSummary | None = None
    response_draft: ResponseDraft | None = None
    review_citations: list[Citation] = Field(default_factory=list)
    safety_result: SafetyResult | None = None
    post_generation_safety_result: SafetyResult | None = None
    final_response: GeneratedResponse | None = None
    failure_code: NonEmptyString | None = None
    review_version: int = Field(default=0, ge=0)
    review_record: ReviewRecord | None = None
    transitions: list[WorkflowTransition] = Field(default_factory=list)
    audit_log: list[AuditEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def terminal_fields_match_status(self) -> "WorkflowRunSnapshot":
        """Keep redacted status fields internally consistent."""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (self.status == WorkflowStatus.FAILED) != (self.failure_code is not None):
            raise ValueError("failure_code must be set only for a failed run")
        if (self.status == WorkflowStatus.COMPLETED) != (
            self.final_response is not None
        ):
            raise ValueError("final_response must be set only for a completed run")
        if self.final_response is not None:
            evidence = self.guideline_evidence
            if (
                evidence is None
                or evidence.assessment is not EvidenceAssessment.SUFFICIENT
                or not self.final_response.citations
            ):
                raise ValueError("completed run requires sufficient cited evidence")
            if evidence.chunk_ids != [
                citation.chunk_id for citation in self.final_response.citations
            ]:
                raise ValueError("run evidence chunk IDs must match final citations")
            if set(evidence.document_ids) != {
                citation.document_id for citation in self.final_response.citations
            }:
                raise ValueError("run evidence document IDs must match final citations")
        if self.response_draft is not None:
            evidence = self.guideline_evidence
            if (
                evidence is None
                or evidence.assessment is not EvidenceAssessment.SUFFICIENT
                or not self.review_citations
            ):
                raise ValueError("response draft requires sufficient review evidence")
            if evidence.chunk_ids != [
                citation.chunk_id for citation in self.review_citations
            ]:
                raise ValueError("review evidence chunk IDs must match draft citations")
            if set(evidence.document_ids) != {
                citation.document_id for citation in self.review_citations
            }:
                raise ValueError(
                    "review evidence document IDs must match draft citations"
                )
        if (
            self.status == WorkflowStatus.PENDING_REVIEW
            and self.requires_human_review is not True
        ):
            raise ValueError("pending review requires the review flag")
        if self.review_record is not None and self.review_record.review_version != (
            self.review_version
        ):
            raise ValueError("review record version must match snapshot version")
        if any(
            event.workflow_id != self.workflow_id
            or event.correlation_id != self.correlation_id
            for event in self.audit_log
        ):
            raise ValueError("audit events must match run identifiers")
        event_ids = [event.event_id for event in self.audit_log]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("audit event IDs must be unique within a run")
        if not self.transitions:
            if self.status != WorkflowStatus.QUEUED:
                raise ValueError("only a queued checkpoint may omit transitions")
            return self
        previous_status = self.transitions[0].from_status
        previous_time = self.created_at
        for transition in self.transitions:
            if transition.from_status != previous_status:
                raise ValueError("run transitions must form a status chain")
            if transition.occurred_at < previous_time:
                raise ValueError("run transition timestamps must be monotonic")
            previous_status = transition.to_status
            previous_time = transition.occurred_at
        if previous_status != self.status or previous_time != self.updated_at:
            raise ValueError("final run transition must match snapshot status and time")
        return self

    @classmethod
    def queued(
        cls,
        *,
        workflow_id: WorkflowId,
        correlation_id: CorrelationId,
        trace_id: TraceId,
        created_at: UtcTimestamp,
    ) -> "WorkflowRunSnapshot":
        """Build the initial redacted checkpoint before graph execution."""

        return cls(
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            status=WorkflowStatus.QUEUED,
            created_at=created_at,
            updated_at=created_at,
        )

    @classmethod
    def from_execution(
        cls,
        execution: WorkflowExecutionResult,
        *,
        trace_id: TraceId,
    ) -> "WorkflowRunSnapshot":
        """Project a full in-memory execution into a redacted checkpoint."""

        workflow = execution.workflow
        return cls(
            workflow_id=workflow.workflow_id,
            correlation_id=workflow.correlation_id,
            trace_id=trace_id,
            status=workflow.status,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            requires_human_review=workflow.requires_human_review,
            guideline_evidence=workflow.guideline_evidence,
            response_draft=workflow.response_draft,
            review_citations=workflow.retrieved_guidelines,
            safety_result=workflow.safety_result,
            post_generation_safety_result=workflow.post_generation_safety_result,
            final_response=workflow.final_response,
            failure_code=workflow.failure_code,
            transitions=execution.transitions,
            audit_log=workflow.audit_log,
        )


class ReviewQueueItem(ContractModel):
    """Redacted queue projection for a pending workflow review."""

    workflow_id: WorkflowId
    correlation_id: CorrelationId
    trace_id: TraceId
    status: WorkflowStatus
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    review_version: int = Field(ge=0)
    requires_human_review: bool
    guideline_evidence: GuidelineEvidenceSummary | None = None
    response_draft: ResponseDraft | None = None
    citations: list[Citation] = Field(default_factory=list)
    safety_result: SafetyResult | None = None
    post_generation_safety_result: SafetyResult | None = None

    @classmethod
    def from_snapshot(cls, snapshot: WorkflowRunSnapshot) -> "ReviewQueueItem":
        """Build the safe reviewer-facing view of one pending checkpoint."""

        return cls(
            workflow_id=snapshot.workflow_id,
            correlation_id=snapshot.correlation_id,
            trace_id=snapshot.trace_id,
            status=snapshot.status,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            review_version=snapshot.review_version,
            requires_human_review=bool(snapshot.requires_human_review),
            guideline_evidence=snapshot.guideline_evidence,
            response_draft=snapshot.response_draft,
            citations=snapshot.review_citations,
            safety_result=snapshot.safety_result,
            post_generation_safety_result=snapshot.post_generation_safety_result,
        )
