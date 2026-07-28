"""Application-owned deterministic safety policy capability."""

from typing import Protocol

from app.domain.clinical import PatientSummary
from app.domain.safety import SafetyResult


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
