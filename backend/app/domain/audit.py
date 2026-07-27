"""Audit-event contracts."""

from enum import StrEnum
from typing import TypeAlias

from pydantic import Field

from app.domain.base import (
    AuditEventId,
    ContractModel,
    CorrelationId,
    NonEmptyString,
    UtcTimestamp,
    WorkflowId,
)

AuditValue: TypeAlias = str | int | float | bool | None


class AuditEventType(StrEnum):
    """Auditable workflow milestones."""

    WORKFLOW_CREATED = "workflow_created"
    STATUS_CHANGED = "status_changed"
    TOOL_CALLED = "tool_called"
    SAFETY_EVALUATED = "safety_evaluated"
    REVIEW_RECORDED = "review_recorded"
    RESPONSE_GENERATED = "response_generated"
    WORKFLOW_FAILED = "workflow_failed"


class ActorType(StrEnum):
    """Origin of an auditable action."""

    USER = "user"
    SYSTEM = "system"
    REVIEWER = "reviewer"


class AuditEvent(ContractModel):
    """Minimal, structured audit record without raw clinical payloads."""

    event_id: AuditEventId
    workflow_id: WorkflowId
    correlation_id: CorrelationId
    event_type: AuditEventType
    occurred_at: UtcTimestamp
    actor_type: ActorType
    actor_id: NonEmptyString | None = None
    details: dict[str, AuditValue] = Field(default_factory=dict)
