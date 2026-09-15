"""Application-owned deterministic safety policy capability."""

from typing import Protocol

from app.domain.clinical import Citation, PatientSummary
from app.domain.safety import SafetyResult
from app.domain.workflow import ResponseDraft


class SafetyPolicyError(RuntimeError):
    """The safety policy could not return a safe structured result."""


class SafetyPolicy(Protocol):
    """Evaluate bounded normalized context using a versioned policy."""

    async def evaluate(
        self,
        *,
        query: str,
        patient: PatientSummary,
    ) -> SafetyResult:
        """Return one validated deterministic safety decision."""


class PostGenerationSafetyPolicy(Protocol):
    """Evaluate a generated draft before it becomes a final response."""

    async def evaluate_draft(
        self,
        *,
        query: str,
        draft: ResponseDraft,
        citations: list[Citation],
    ) -> SafetyResult:
        """Return one validated post-generation safety decision."""
