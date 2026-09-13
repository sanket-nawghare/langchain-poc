"""Run-scoped dependencies for deterministic workflow execution."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.rag.retrieval import GuidelineRetriever
from app.tools.intent import IntentClassifier
from app.tools.patient import PatientSummaryReader
from app.tools.response import ResponseGenerator
from app.tools.safety import PostGenerationSafetyPolicy, SafetyPolicy


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
class WorkflowExecutionPolicy:
    """Bounded execution policy for external workflow capabilities."""

    timeout_seconds: float = 10.0
    max_retries: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError(
                "workflow timeout must be greater than zero and at most 30"
            )
        if not 0 <= self.max_retries <= 3:
            raise ValueError("workflow retries must be between zero and three")


@dataclass(frozen=True)
class WorkflowRuntime:
    """Immutable dependencies injected into one LangGraph run."""

    clock: WorkflowClock
    intent_classifier: IntentClassifier
    patient_summary_reader: PatientSummaryReader
    safety_policy: SafetyPolicy
    post_generation_safety_policy: PostGenerationSafetyPolicy
    response_generator: ResponseGenerator
    audit_event_ids: AuditEventIdFactory
    guideline_retriever: GuidelineRetriever | None = None
    execution_policy: WorkflowExecutionPolicy = field(
        default_factory=WorkflowExecutionPolicy
    )
    response_execution_policy: WorkflowExecutionPolicy | None = None
