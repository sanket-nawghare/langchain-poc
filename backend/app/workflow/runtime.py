"""Run-scoped dependencies for deterministic workflow execution."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.tools.intent import IntentClassifier
from app.tools.patient import PatientSummaryReader
from app.tools.response import ResponseGenerator
from app.tools.safety import SafetyPolicy


class WorkflowClock(Protocol):
    """Application-owned source of timezone-aware execution timestamps."""

    def now(self) -> datetime:
        """Return the current timezone-aware time."""


class SystemWorkflowClock:
    """Production clock implementation."""

    def now(self) -> datetime:
        """Return the current UTC time."""

        return datetime.now(UTC)


class AuditEventIdFactory(Protocol):
    """Application-owned source of audit event identifiers."""

    def new(self) -> UUID:
        """Return a new audit event identifier."""


class RandomAuditEventIdFactory:
    """Production UUID source for audit events."""

    def new(self) -> UUID:
        """Return a random UUID4 identifier."""

        return uuid4()


@dataclass(frozen=True)
class WorkflowRuntime:
    """Immutable dependencies injected into one LangGraph run."""

    clock: WorkflowClock
    intent_classifier: IntentClassifier
    patient_summary_reader: PatientSummaryReader
    safety_policy: SafetyPolicy
    response_generator: ResponseGenerator
    audit_event_ids: AuditEventIdFactory
