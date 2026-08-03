"""Provider-neutral vector-store capability and safe failures."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.guideline_index import (
    GuidelineIndexSnapshot,
    GuidelineIngestionResult,
    GuidelineVectorRecord,
)


class GuidelineVectorStoreError(RuntimeError):
    """Base vector-store failure safe to handle outside an adapter."""


class GuidelineVectorStoreUnavailableError(GuidelineVectorStoreError):
    """The configured vector store could not be reached."""


class GuidelineVectorStoreSchemaError(GuidelineVectorStoreError):
    """The application collection has an incompatible schema."""


class GuidelineVectorStoreWriteError(GuidelineVectorStoreError):
    """A bounded collection mutation did not complete."""


class GuidelineVectorStoreVerificationError(GuidelineVectorStoreError):
    """Stored identities or counts differ from the expected corpus."""


class GuidelineVectorStore(Protocol):
    """Replaceable store for one complete versioned guideline collection."""

    def sync(
        self,
        records: Sequence[GuidelineVectorRecord],
    ) -> GuidelineIngestionResult:
        """Idempotently make the collection exactly match the supplied records."""

    def verify(
        self,
        records: Sequence[GuidelineVectorRecord],
    ) -> GuidelineIndexSnapshot:
        """Verify exact IDs, metadata, document counts, and checksums."""

    def reset(self) -> None:
        """Delete only this implementation's application-owned collection."""

    def close(self) -> None:
        """Release transport resources."""
