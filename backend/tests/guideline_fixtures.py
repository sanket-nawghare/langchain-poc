"""Reviewed provider-neutral guideline evidence used by workflow tests."""

from datetime import date

from app.domain.clinical import Citation
from app.domain.guidelines import (
    EvidenceAssessment,
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineRetrievalMatch,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
    GuidelineSource,
    GuidelineUsePermission,
)


def sufficient_guideline_result() -> GuidelineRetrievalResult:
    """Return one strictly linked synthetic sufficient-evidence result."""

    source = GuidelineSource(
        document_id="who-synthetic-guideline",
        title="Reviewed synthetic guideline",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://example.test/reviewed-guideline",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2026, 1, 1),
        version="2026-v1",
        accessed_at=date(2026, 7, 1),
        license_name="Reviewed test permission",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 7, 1),
        license_review_note="Test-only reviewed source metadata.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256="1" * 64,
        supported_topics=["synthetic condition"],
    )
    chunk = GuidelineChunk(
        chunk_id="who-synthetic-guideline.0",
        document_id=source.document_id,
        text="Reviewed bounded evidence chunk.",
        content_sha256="2" * 64,
        sequence=0,
        page=1,
    )
    match = GuidelineRetrievalMatch(
        source=source,
        chunk=chunk,
        citation=Citation(
            document_id=source.document_id,
            chunk_id=chunk.chunk_id,
            title=source.title,
            publisher=source.publisher.value,
            source_url=source.canonical_url,
            page=chunk.page,
            excerpt="Bounded evidence excerpt.",
        ),
        relevance_score=0.9,
        rank=1,
    )
    return GuidelineRetrievalResult(
        assessment=EvidenceAssessment.SUFFICIENT,
        policy_version="retrieval-v1",
        query_fingerprint="0" * 64,
        matches=[match],
    )


class SufficientGuidelineRetriever:
    """Return the shared sufficient-evidence fixture without provider objects."""

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        del request
        return sufficient_guideline_result()

    async def close(self) -> None:
        return None
