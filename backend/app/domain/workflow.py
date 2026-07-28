"""Typed workflow state and response contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from app.domain.audit import AuditEvent
from app.domain.base import (
    ContractModel,
    CorrelationId,
    NonEmptyString,
    PatientId,
    UtcTimestamp,
    WorkflowId,
    WorkflowQuery,
)
from app.domain.clinical import Citation, PatientSummary
from app.domain.safety import SafetyResult


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

    answer: NonEmptyString
    citations: list[Citation] = Field(default_factory=list)
    disclaimer: NonEmptyString


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
    retrieved_guidelines: list[Citation] = Field(default_factory=list)
    safety_result: SafetyResult | None = None
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
        if self.safety_result is None:
            return self
        if self.requires_human_review != self.safety_result.requires_human_review:
            raise ValueError("requires_human_review must match safety_result")
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
