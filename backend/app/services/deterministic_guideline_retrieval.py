"""Deterministic evidence qualification over trusted vector candidates."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from app.domain.clinical import Citation
from app.domain.guideline_index import (
    GuidelineVectorCandidate,
    GuidelineVectorSearchRequest,
)
from app.domain.guidelines import (
    EvidenceAssessment,
    GuidelineRetrievalMatch,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
    GuidelineSource,
)
from app.rag.embeddings import GuidelineEmbeddingError, GuidelineEmbeddingModel
from app.rag.retrieval import (
    GuidelineConflictDetector,
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
    GuidelineSourceCatalog,
    eligible_guideline_sources,
    trusted_source_for_candidate,
)
from app.rag.vector_store import (
    GuidelineCandidateStore,
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
    GuidelineVectorStoreVerificationError,
)
from app.services.pypdf_guidelines import PARSER_VERSION
from app.services.weaviate_guideline_index import GUIDELINE_SCHEMA_VERSION

GUIDELINE_RETRIEVAL_POLICY_VERSION = "deterministic-guideline-retrieval-v1"
GUIDELINE_CANDIDATE_LIMIT = 32
GUIDELINE_RELEVANCE_THRESHOLD = 0.45
CHUNK_COVERAGE_WEIGHT = 0.60
SOURCE_COVERAGE_WEIGHT = 0.25
VECTOR_AFFINITY_WEIGHT = 0.15
MAX_CITATION_EXCERPT = 500

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_GENERIC_TERMS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "for",
        "from",
        "guidance",
        "how",
        "in",
        "is",
        "it",
        "manage",
        "management",
        "of",
        "on",
        "or",
        "recommend",
        "recommended",
        "should",
        "the",
        "to",
        "treat",
        "treatment",
        "use",
        "used",
        "what",
        "when",
        "which",
        "with",
    }
)


class NoKnownGuidelineConflicts:
    """Starter-corpus policy: no reviewed material conflict is configured."""

    def has_conflict(self, matches: Sequence[GuidelineRetrievalMatch]) -> bool:
        del matches
        return False


class DeterministicGuidelineRetriever:
    """Retrieve, validate, qualify, rank, and cite reviewed local evidence."""

    def __init__(
        self,
        *,
        catalog: GuidelineSourceCatalog,
        embedding_model: GuidelineEmbeddingModel,
        candidate_store: GuidelineCandidateStore,
        conflict_detector: GuidelineConflictDetector | None = None,
    ) -> None:
        self._catalog = catalog
        self._embedding_model = embedding_model
        self._candidate_store = candidate_store
        self._conflict_detector = conflict_detector or NoKnownGuidelineConflicts()

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        fingerprint = query_fingerprint(request.clinical_query)
        sources = eligible_guideline_sources(self._catalog, request)
        if not sources:
            return _insufficient(fingerprint)

        try:
            vectors = self._embedding_model.embed([request.clinical_query])
        except GuidelineEmbeddingError as error:
            raise GuidelineRetrievalResponseError(
                "guideline query embedding is invalid"
            ) from error
        if len(vectors) != 1:
            raise GuidelineRetrievalResponseError(
                "guideline query embedding count is invalid"
            )

        search_request = GuidelineVectorSearchRequest(
            schema_version=GUIDELINE_SCHEMA_VERSION,
            parser_version=PARSER_VERSION,
            embedding_model=self._embedding_model.model_id,
            embedding_dimensions=self._embedding_model.dimensions,
            vector=list(vectors[0]),
            eligible_document_ids=[source.document_id for source in sources],
            candidate_limit=GUIDELINE_CANDIDATE_LIMIT,
        )
        try:
            candidates = await self._candidate_store.search(search_request)
        except GuidelineVectorStoreTimeoutError as error:
            raise GuidelineRetrievalTimeoutError(
                "guideline retrieval timed out"
            ) from error
        except GuidelineVectorStoreUnavailableError as error:
            raise GuidelineRetrievalUnavailableError(
                "guideline retrieval is unavailable"
            ) from error
        except (
            GuidelineVectorStoreSchemaError,
            GuidelineVectorStoreVerificationError,
        ) as error:
            raise GuidelineRetrievalResponseError(
                "guideline retrieval response is invalid"
            ) from error

        trusted_sources = {source.document_id: source for source in sources}
        qualified = [
            scored
            for candidate in candidates
            if (
                scored := _score_candidate(
                    candidate,
                    trusted_source_for_candidate(candidate, trusted_sources),
                    request.clinical_query,
                )
            )[0]
            >= GUIDELINE_RELEVANCE_THRESHOLD
        ]
        qualified.sort(
            key=lambda item: (
                -item[0],
                item[1].distance,
                item[1].chunk.chunk_id,
                str(item[1].object_id),
            )
        )
        selected = qualified[: request.top_k]
        if not selected:
            return _insufficient(fingerprint)

        matches = [
            _match(
                candidate,
                source,
                score=score,
                rank=rank,
                query=request.clinical_query,
            )
            for rank, (score, candidate, source) in enumerate(selected, start=1)
        ]
        conflict = self._conflict_detector.has_conflict(matches)
        if conflict and len(matches) < 2:
            raise GuidelineRetrievalResponseError(
                "conflict policy requires at least two evidence matches"
            )
        return GuidelineRetrievalResult(
            assessment=(
                EvidenceAssessment.CONFLICTING
                if conflict
                else EvidenceAssessment.SUFFICIENT
            ),
            policy_version=GUIDELINE_RETRIEVAL_POLICY_VERSION,
            query_fingerprint=fingerprint,
            matches=matches,
        )

    async def close(self) -> None:
        await self._candidate_store.close()


def query_fingerprint(query: str) -> str:
    """Hash a stable normalized query without retaining its text."""

    normalized = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _insufficient(fingerprint: str) -> GuidelineRetrievalResult:
    return GuidelineRetrievalResult(
        assessment=EvidenceAssessment.INSUFFICIENT,
        policy_version=GUIDELINE_RETRIEVAL_POLICY_VERSION,
        query_fingerprint=fingerprint,
    )


def _score_candidate(
    candidate: GuidelineVectorCandidate,
    source: GuidelineSource,
    query: str,
) -> tuple[float, GuidelineVectorCandidate, GuidelineSource]:
    query_terms = _meaningful_terms(query)
    if not query_terms:
        return (0.0, candidate, source)
    chunk_terms = _meaningful_terms(candidate.chunk.text)
    source_terms = _meaningful_terms(" ".join((source.title, *source.supported_topics)))
    chunk_coverage = len(query_terms & chunk_terms) / len(query_terms)
    source_coverage = len(query_terms & source_terms) / len(query_terms)
    if source_coverage == 0:
        return (0.0, candidate, source)
    vector_affinity = max(0.0, min(1.0, 1.0 - candidate.distance / 2.0))
    score = (
        CHUNK_COVERAGE_WEIGHT * chunk_coverage
        + SOURCE_COVERAGE_WEIGHT * source_coverage
        + VECTOR_AFFINITY_WEIGHT * vector_affinity
    )
    return (round(score, 6), candidate, source)


def _meaningful_terms(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for raw in _TOKEN_PATTERN.findall(text.casefold()):
        normalized = _normalize_term(raw)
        if (
            len(normalized) > 1
            and raw not in _GENERIC_TERMS
            and normalized not in _GENERIC_TERMS
        ):
            terms.add(normalized)
    return frozenset(terms)


def _normalize_term(term: str) -> str:
    if len(term) > 5 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 4 and term.endswith("ed"):
        return term[:-2]
    if len(term) > 4 and term.endswith("es"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s"):
        return term[:-1]
    return term


def _match(
    candidate: GuidelineVectorCandidate,
    source: GuidelineSource,
    *,
    score: float,
    rank: int,
    query: str,
) -> GuidelineRetrievalMatch:
    return GuidelineRetrievalMatch(
        source=source,
        chunk=candidate.chunk,
        citation=Citation(
            document_id=source.document_id,
            chunk_id=candidate.chunk.chunk_id,
            title=source.title,
            publisher=source.publisher.value,
            source_url=source.canonical_url,
            page=candidate.chunk.page,
            excerpt=_excerpt(candidate.chunk.text, _meaningful_terms(query)),
        ),
        relevance_score=score,
        rank=rank,
    )


def _excerpt(text: str, query_terms: frozenset[str]) -> str:
    if len(text) <= MAX_CITATION_EXCERPT:
        return text
    anchor = 0
    for match in _TOKEN_PATTERN.finditer(text.casefold()):
        if _normalize_term(match.group()) in query_terms:
            anchor = match.start()
            break
    start = max(0, min(anchor - 160, len(text) - 496))
    end = min(len(text), start + 496)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = f"… {excerpt}"
    if end < len(text):
        excerpt = f"{excerpt} …"
    return excerpt[:MAX_CITATION_EXCERPT]
