"""Application-owned intent classification capability."""

from typing import Protocol

from app.domain.workflow import IntentClassification


class IntentClassificationError(RuntimeError):
    """The classifier could not return a safe structured result."""


class IntentClassifier(Protocol):
    """Classify one bounded query without exposing provider response objects."""

    async def classify(self, query: str) -> IntentClassification:
        """Return one validated supported intent or the unknown fallback."""
