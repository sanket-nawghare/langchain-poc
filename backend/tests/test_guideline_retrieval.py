"""Deterministic guideline scoring, qualification, and citation tests."""

from datetime import date
from hashlib import sha256
from uuid import UUID

import pytest

from app.domain import (
    EvidenceAssessment,
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineRetrievalRequest,
    GuidelineSource,
    GuidelineUsePermission,
    GuidelineVectorCandidate,
    GuidelineVectorSearchRequest,
)
from app.rag import (
    GuidelineEmbeddingResponseError,
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
    GuidelineVectorStoreVerificationError,
)
from app.services.deterministic_guideline_embeddings import (
    DETERMINISTIC_EMBEDDING_DIMENSIONS,
    DETERMINISTIC_EMBEDDING_MODEL,
    DeterministicGuidelineEmbeddingModel,
)
from app.services.deterministic_guideline_retrieval import (
    GUIDELINE_CANDIDATE_LIMIT,
    GUIDELINE_RELEVANCE_THRESHOLD,
    GUIDELINE_RETRIEVAL_POLICY_VERSION,
    DeterministicGuidelineRetriever,
    query_fingerprint,
)
from app.services.pypdf_guidelines import PARSER_VERSION
from app.services.weaviate_guideline_index import GUIDELINE_SCHEMA_VERSION

SOURCE_CHECKSUM = sha256(b"trusted reviewed source").hexdigest()


def source() -> GuidelineSource:
    return GuidelineSource(
        document_id="who-hypertension-2021",
        title="Guideline for pharmacological treatment of hypertension in adults",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://www.who.int/publications/i/item/9789240033986",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2021, 8, 24),
        version="ISBN 978-92-4-003398-6",
        accessed_at=date(2026, 8, 3),
        license_name="CC BY-NC-SA 3.0 IGO",
        license_url="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 8, 3),
        license_review_note="Reviewed synthetic source metadata fixture.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256=SOURCE_CHECKSUM,
        supported_topics=[
            "adult hypertension",
            "blood pressure targets",
            "pharmacological treatment",
        ],
    )


class StaticCatalog:
    def __init__(self, sources: tuple[GuidelineSource, ...]) -> None:
        self._sources = sources

    def sources(self) -> tuple[GuidelineSource, ...]:
        return self._sources


class RecordingCandidateStore:
    def __init__(
        self,
        candidates: tuple[GuidelineVectorCandidate, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.candidates = candidates
        self.error = error
        self.request: GuidelineVectorSearchRequest | None = None
        self.closed = False

    async def search(
        self,
        request: GuidelineVectorSearchRequest,
    ) -> tuple[GuidelineVectorCandidate, ...]:
        self.request = request
        if self.error is not None:
            raise self.error
        return self.candidates

    async def close(self) -> None:
        self.closed = True


class AlwaysConflict:
    def has_conflict(self, matches: object) -> bool:
        del matches
        return True


class FailingEmbeddingModel:
    @property
    def model_id(self) -> str:
        return DETERMINISTIC_EMBEDDING_MODEL

    @property
    def dimensions(self) -> int:
        return DETERMINISTIC_EMBEDDING_DIMENSIONS

    def embed(self, texts: object) -> tuple[tuple[float, ...], ...]:
        del texts
        raise GuidelineEmbeddingResponseError("provider embedding payload")


def candidate(
    chunk_id: str,
    *,
    text: str,
    distance: float,
    object_id: UUID,
) -> GuidelineVectorCandidate:
    trusted = source()
    return GuidelineVectorCandidate(
        object_id=object_id,
        schema_version=GUIDELINE_SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
        source_sha256=trusted.content_sha256,
        document_version=trusted.version,
        publisher=trusted.publisher,
        publication_date=trusted.publication_date,
        lifecycle_status=trusted.lifecycle_status,
        chunk=GuidelineChunk(
            chunk_id=chunk_id,
            document_id=trusted.document_id,
            text=text,
            content_sha256=sha256(text.encode()).hexdigest(),
            sequence=1,
            page=12,
            section="BLOOD PRESSURE TARGETS",
        ),
        distance=distance,
    )


def retriever(
    store: RecordingCandidateStore,
    *,
    catalog: StaticCatalog | None = None,
    conflict: AlwaysConflict | None = None,
) -> DeterministicGuidelineRetriever:
    return DeterministicGuidelineRetriever(
        catalog=catalog or StaticCatalog((source(),)),
        embedding_model=DeterministicGuidelineEmbeddingModel(),
        candidate_store=store,
        conflict_detector=conflict,
    )


def request(
    query: str = "What blood pressure target is recommended for adults?",
    *,
    top_k: int = 5,
) -> GuidelineRetrievalRequest:
    return GuidelineRetrievalRequest(
        clinical_query=query,
        top_k=top_k,
        as_of=date(2026, 8, 3),
    )


@pytest.mark.anyio
async def test_retriever_builds_trusted_ranked_citations() -> None:
    long_text = (
        "Context without the key phrase. " * 30
        + "For adults, the blood pressure target is described in this section."
    )
    second_text = "Adult blood pressure target evidence from a later candidate."
    store = RecordingCandidateStore(
        (
            candidate(
                "who-hypertension-2021.p0013.c000.bbbbbbbbbbbb",
                text=second_text,
                distance=0.7,
                object_id=UUID("00000000-0000-0000-0000-000000000002"),
            ),
            candidate(
                "who-hypertension-2021.p0012.c000.aaaaaaaaaaaa",
                text=long_text,
                distance=0.8,
                object_id=UUID("00000000-0000-0000-0000-000000000001"),
            ),
        )
    )

    result = await retriever(store).retrieve(request(top_k=2))

    assert result.assessment is EvidenceAssessment.SUFFICIENT
    assert result.policy_version == GUIDELINE_RETRIEVAL_POLICY_VERSION
    assert result.query_fingerprint == query_fingerprint(
        "What blood pressure target is recommended for adults?"
    )
    assert [match.rank for match in result.matches] == [1, 2]
    assert all(
        match.relevance_score >= GUIDELINE_RELEVANCE_THRESHOLD
        for match in result.matches
    )
    assert result.matches[0].citation.source_url == source().canonical_url
    assert result.matches[0].citation.chunk_id == result.matches[0].chunk.chunk_id
    assert result.matches[0].citation.page == 12
    assert result.matches[0].citation.excerpt is not None
    assert len(result.matches[0].citation.excerpt) <= 500
    assert "blood pressure target" in result.matches[0].citation.excerpt
    assert store.request is not None
    assert store.request.candidate_limit == GUIDELINE_CANDIDATE_LIMIT
    assert store.request.eligible_document_ids == [source().document_id]


@pytest.mark.anyio
async def test_stable_tie_breaking_ignores_provider_order() -> None:
    text = "Adult blood pressure target guidance."
    later = candidate(
        "who-hypertension-2021.p0012.c001.bbbbbbbbbbbb",
        text=text,
        distance=0.7,
        object_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    earlier = candidate(
        "who-hypertension-2021.p0012.c000.aaaaaaaaaaaa",
        text=text,
        distance=0.7,
        object_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    result = await retriever(RecordingCandidateStore((later, earlier))).retrieve(
        request(top_k=2)
    )

    assert [match.chunk.chunk_id for match in result.matches] == [
        earlier.chunk.chunk_id,
        later.chunk.chunk_id,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    [
        "What vaccination schedule is recommended for children?",
        "How should an ankle fracture be treated?",
        "What telescope should observe distant galaxies?",
        "What guidance should be used?",
    ],
)
async def test_unrelated_or_generic_queries_are_insufficient(query: str) -> None:
    unrelated = candidate(
        "who-hypertension-2021.p0012.c000.aaaaaaaaaaaa",
        text="A treatment passage that does not address the question.",
        distance=0.1,
        object_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    result = await retriever(RecordingCandidateStore((unrelated,))).retrieve(
        request(query)
    )

    assert result.assessment is EvidenceAssessment.INSUFFICIENT
    assert result.matches == []


@pytest.mark.anyio
async def test_no_eligible_source_is_insufficient_without_store_query() -> None:
    store = RecordingCandidateStore()
    future_request = GuidelineRetrievalRequest(
        clinical_query="adult blood pressure target",
        as_of=date(2020, 1, 1),
    )

    result = await retriever(store).retrieve(future_request)

    assert result.assessment is EvidenceAssessment.INSUFFICIENT
    assert store.request is None


@pytest.mark.anyio
async def test_empty_candidate_result_is_valid_insufficient() -> None:
    result = await retriever(RecordingCandidateStore()).retrieve(request())

    assert result.assessment is EvidenceAssessment.INSUFFICIENT
    assert result.matches == []


@pytest.mark.anyio
async def test_embedding_failure_maps_to_safe_response_error() -> None:
    store = RecordingCandidateStore()
    service = DeterministicGuidelineRetriever(
        catalog=StaticCatalog((source(),)),
        embedding_model=FailingEmbeddingModel(),
        candidate_store=store,
    )

    with pytest.raises(GuidelineRetrievalResponseError) as error:
        await service.retrieve(request())

    assert "provider embedding payload" not in str(error.value)
    assert store.request is None


@pytest.mark.anyio
async def test_explicit_conflict_requires_and_returns_two_matches() -> None:
    first = candidate(
        "who-hypertension-2021.p0012.c000.aaaaaaaaaaaa",
        text="Adult blood pressure target guidance.",
        distance=0.6,
        object_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    second = candidate(
        "who-hypertension-2021.p0013.c000.bbbbbbbbbbbb",
        text="Adult blood pressure target evidence.",
        distance=0.7,
        object_id=UUID("00000000-0000-0000-0000-000000000002"),
    )

    result = await retriever(
        RecordingCandidateStore((first, second)),
        conflict=AlwaysConflict(),
    ).retrieve(request(top_k=2))

    assert result.assessment is EvidenceAssessment.CONFLICTING
    assert len(result.matches) == 2

    with pytest.raises(GuidelineRetrievalResponseError, match="at least two"):
        await retriever(
            RecordingCandidateStore((first,)),
            conflict=AlwaysConflict(),
        ).retrieve(request(top_k=1))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("store_error", "expected_error"),
    [
        (
            GuidelineVectorStoreTimeoutError("provider details"),
            GuidelineRetrievalTimeoutError,
        ),
        (
            GuidelineVectorStoreUnavailableError("provider details"),
            GuidelineRetrievalUnavailableError,
        ),
        (
            GuidelineVectorStoreSchemaError("provider details"),
            GuidelineRetrievalResponseError,
        ),
        (
            GuidelineVectorStoreVerificationError("provider details"),
            GuidelineRetrievalResponseError,
        ),
    ],
)
async def test_store_failures_map_to_safe_retrieval_errors(
    store_error: Exception,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error) as error:
        await retriever(RecordingCandidateStore(error=store_error)).retrieve(request())

    assert "provider details" not in str(error.value)


@pytest.mark.anyio
async def test_retriever_closes_candidate_store() -> None:
    store = RecordingCandidateStore()
    service = retriever(store)

    await service.close()

    assert store.closed is True


def test_query_fingerprint_normalizes_case_unicode_and_whitespace() -> None:
    assert query_fingerprint("  BLOOD   pressure  ") == query_fingerprint(
        "blood pressure"
    )
    assert query_fingerprint("ＡＤＵＬＴ") == query_fingerprint("adult")
