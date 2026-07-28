"""Application-owned structured response-generation capability."""

from typing import Protocol

from app.domain.clinical import Citation, PatientSummary
from app.domain.workflow import ResponseDraft


class ResponseGenerationError(RuntimeError):
    """The response generator could not return a safe structured draft."""


class ResponseGenerationTimeoutError(ResponseGenerationError):
    """The response generator exhausted its bounded execution time."""


class ResponseGenerator(Protocol):
    """Draft bounded educational text without controlling qualifications."""

    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        """Return answer text in the application-owned draft contract."""
