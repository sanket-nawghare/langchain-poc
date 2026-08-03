"""Application-owned guideline retrieval capability and safe failures."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.guideline_index import GuidelineVectorCandidate
from app.domain.guidelines import (
    GuidelineRetrievalMatch,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
    GuidelineSource,
)


class GuidelineRetrievalError(RuntimeError):
    """Base retrieval failure safe to map beyond an adapter boundary."""


class GuidelineRetrievalTimeoutError(GuidelineRetrievalError):
    """Retrieval exhausted its bounded timeout behavior."""


class GuidelineRetrievalUnavailableError(GuidelineRetrievalError):
    """The retrieval dependency is unavailable."""


class GuidelineRetrievalResponseError(GuidelineRetrievalError):
    """A retrieval provider returned malformed or unsafe data."""


class GuidelineSourceCatalog(Protocol):
    """Application-owned access to reviewed source records."""

    def sources(self) -> tuple[GuidelineSource, ...]:
        """Return the complete strictly validated source catalog."""


class GuidelineConflictDetector(Protocol):
    """Deterministic application policy for explicit evidence conflicts."""

    def has_conflict(self, matches: Sequence[GuidelineRetrievalMatch]) -> bool:
        """Return true only for a configured material conflict."""


def eligible_guideline_sources(
    catalog: GuidelineSourceCatalog,
    request: GuidelineRetrievalRequest,
) -> tuple[GuidelineSource, ...]:
    """Derive a stable eligible source set without consulting the vector store."""

    allowed_publishers = set(request.publishers)
    return tuple(
        sorted(
            (
                source
                for source in catalog.sources()
                if source.is_indexable
                and source.publication_date <= request.as_of
                and (not allowed_publishers or source.publisher in allowed_publishers)
            ),
            key=lambda source: source.document_id,
        )
    )


def trusted_source_for_candidate(
    candidate: GuidelineVectorCandidate,
    trusted_sources: Mapping[str, GuidelineSource],
) -> GuidelineSource:
    """Require stored source identity to agree with an eligible trusted source."""

    source = trusted_sources.get(candidate.chunk.document_id)
    if source is None:
        raise GuidelineRetrievalResponseError(
            "retrieval candidate references an ineligible document"
        )
    if (
        candidate.source_sha256 != source.content_sha256
        or candidate.document_version != source.version
        or candidate.publisher is not source.publisher
        or candidate.publication_date != source.publication_date
        or candidate.lifecycle_status is not source.lifecycle_status
    ):
        raise GuidelineRetrievalResponseError(
            "retrieval candidate source metadata does not match trusted catalog"
        )
    return source


class GuidelineRetriever(Protocol):
    """Provider-neutral asynchronous clinical-guideline retrieval."""

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        """Return a normalized evidence decision or raise a typed safe failure."""

    async def close(self) -> None:
        """Release retrieval dependency resources."""
