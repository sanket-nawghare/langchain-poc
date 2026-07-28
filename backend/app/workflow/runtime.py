"""Run-scoped dependencies for deterministic workflow execution."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.tools.intent import IntentClassifier


class WorkflowClock(Protocol):
    """Application-owned source of timezone-aware execution timestamps."""

    def now(self) -> datetime:
        """Return the current timezone-aware time."""


class SystemWorkflowClock:
    """Production clock implementation."""

    def now(self) -> datetime:
        """Return the current UTC time."""

        return datetime.now(UTC)


@dataclass(frozen=True)
class WorkflowRuntime:
    """Immutable dependencies injected into one LangGraph run."""

    clock: WorkflowClock
    intent_classifier: IntentClassifier
