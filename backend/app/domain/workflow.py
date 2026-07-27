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
)
from app.domain.clinical import Citation, PatientSummary
from app.domain.safety import SafetyResult


class Intent(StrEnum):
    """Supported and safely handled request intents."""

    CLINICAL_QA = "clinical_qa"
    UNKNOWN = "unknown"


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


class WorkflowState(ContractModel):
    """Provider-neutral state exchanged by future LangGraph nodes."""

    workflow_id: WorkflowId
    correlation_id: CorrelationId
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    status: WorkflowStatus = WorkflowStatus.QUEUED
    user_query: NonEmptyString = Field(max_length=4000)
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

        if self.safety_result is None:
            return self
        if (
            self.requires_human_review
            != self.safety_result.requires_human_review
        ):
            raise ValueError(
                "requires_human_review must match safety_result"
            )
        return self
