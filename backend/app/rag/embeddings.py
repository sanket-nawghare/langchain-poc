"""Application-owned embedding capability and safe failures."""

from collections.abc import Sequence
from typing import Protocol


class GuidelineEmbeddingError(RuntimeError):
    """Base error for bounded guideline embedding failures."""


class GuidelineEmbeddingResponseError(GuidelineEmbeddingError):
    """An embedding implementation returned malformed vectors."""


class GuidelineEmbeddingModel(Protocol):
    """Replaceable synchronous embedding capability used by local ingestion."""

    @property
    def model_id(self) -> str:
        """Return a stable identifier that changes when vectors can change."""

    @property
    def dimensions(self) -> int:
        """Return the exact output vector width."""

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed a bounded ordered text batch without changing its cardinality."""
