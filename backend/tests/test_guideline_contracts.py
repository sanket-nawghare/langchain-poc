"""Phase 3.1 guideline provenance and retrieval contract tests."""

from datetime import date
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.domain import (
    Citation,
    EvidenceAssessment,
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineEvidenceSummary,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineRetrievalMatch,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
    GuidelineSource,
    GuidelineUsePermission,
    ParsedGuidelineDocument,
)
from app.rag import (
    GuidelineRetrievalError,
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
)

CHECKSUM = sha256(b"reviewed synthetic guideline fixture").hexdigest()
QUERY_FINGERPRINT = sha256(b"deidentified clinical question").hexdigest()


def source_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "document_id": "who-guideline-2026-v1",
        "title": "Reviewed guideline metadata fixture",
        "publisher": GuidelinePublisher.WHO,
        "canonical_url": "https://example.test/guidelines/reviewed",
        "document_format": GuidelineDocumentFormat.PDF,
        "publication_date": date(2026, 1, 2),
        "version": "2026-v1",
        "accessed_at": date(2026, 7, 30),
        "license_name": "Reviewed test permission",
        "license_url": "https://example.test/license",
        "use_permission": GuidelineUsePermission.LOCAL_INDEX_ONLY,
        "license_reviewed_at": date(2026, 7, 30),
        "license_review_note": "Test-only metadata; no source content included.",
        "lifecycle_status": GuidelineLifecycleStatus.CURRENT,
        "content_sha256": CHECKSUM,
        "supported_topics": ["synthetic metabolic scenario"],
    }
    values.update(overrides)
    return values


def source(**overrides: object) -> GuidelineSource:
    return GuidelineSource.model_validate(source_values(**overrides))


def chunk_values(sequence: int = 0, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "chunk_id": f"who-guideline-2026-v1.{sequence}",
        "document_id": "who-guideline-2026-v1",
        "text": "Bounded synthetic text used only to exercise the contract.",
        "content_sha256": sha256(f"chunk-{sequence}".encode()).hexdigest(),
        "sequence": sequence,
        "page": sequence + 1,
        "section": "Synthetic section",
    }
    values.update(overrides)
    return values


def match(rank: int = 1) -> GuidelineRetrievalMatch:
    reviewed_source = source()
    reviewed_chunk = GuidelineChunk.model_validate(chunk_values(rank - 1))
    return GuidelineRetrievalMatch(
        source=reviewed_source,
        chunk=reviewed_chunk,
        citation=Citation(
            document_id=reviewed_source.document_id,
            chunk_id=reviewed_chunk.chunk_id,
            title=reviewed_source.title,
            publisher=reviewed_source.publisher.value,
            source_url=reviewed_source.canonical_url,
            page=reviewed_chunk.page,
            excerpt="Bounded supporting excerpt.",
        ),
        relevance_score=0.9,
        rank=rank,
    )


def test_source_serializes_without_provider_objects() -> None:
    reviewed_source = source()

    assert reviewed_source.is_indexable is True
    assert reviewed_source.model_dump(mode="json") == {
        **source_values(),
        "publisher": "who",
        "canonical_url": "https://example.test/guidelines/reviewed",
        "document_format": "pdf",
        "publication_date": "2026-01-02",
        "accessed_at": "2026-07-30",
        "license_url": "https://example.test/license",
        "use_permission": "local_index_only",
        "license_reviewed_at": "2026-07-30",
        "lifecycle_status": "current",
        "language": "en",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"publisher": "unreviewed-publisher"}, "publisher"),
        ({"document_format": "docx"}, "document_format"),
        ({"document_id": "Provider ID"}, "document_id"),
        ({"content_sha256": "not-a-checksum"}, "content_sha256"),
        ({"supported_topics": ["duplicate", "duplicate"]}, "unique"),
        ({"supported_topics": ["x"] * 17}, "at most 16"),
    ],
)
def test_source_rejects_unapproved_or_unbounded_metadata(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GuidelineSource.model_validate(source_values(**overrides))


def test_source_requires_valid_review_chronology() -> None:
    with pytest.raises(ValidationError, match="publication_date"):
        source(publication_date=date(2026, 8, 1))
    with pytest.raises(ValidationError, match="license_reviewed_at"):
        source(license_reviewed_at=date(2026, 8, 1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"use_permission": GuidelineUsePermission.LINK_ONLY},
        {"use_permission": GuidelineUsePermission.PROHIBITED},
        {"lifecycle_status": GuidelineLifecycleStatus.SUPERSEDED},
        {"lifecycle_status": GuidelineLifecycleStatus.WITHDRAWN},
    ],
)
def test_source_exposes_non_indexable_review_decisions(
    overrides: dict[str, object],
) -> None:
    assert source(**overrides).is_indexable is False


def test_chunk_and_citation_text_are_bounded() -> None:
    with pytest.raises(ValidationError, match="at most 3000"):
        GuidelineChunk.model_validate(chunk_values(text="x" * 3001))
    with pytest.raises(ValidationError, match="at most 500"):
        Citation(
            document_id="document-1",
            chunk_id="chunk-1",
            title="Title",
            publisher="who",
            source_url="https://example.test/guideline",
            excerpt="x" * 501,
        )


def test_parsed_document_requires_contiguous_owned_chunks() -> None:
    reviewed_source = source()
    first = GuidelineChunk.model_validate(chunk_values())
    second = GuidelineChunk.model_validate(chunk_values(1))

    parsed = ParsedGuidelineDocument(
        parser_version="deterministic-pypdf-v1",
        source=reviewed_source,
        chunks=[first, second],
    )
    assert [chunk.sequence for chunk in parsed.chunks] == [0, 1]

    with pytest.raises(ValidationError, match="ordered and contiguous"):
        ParsedGuidelineDocument(
            parser_version="deterministic-pypdf-v1",
            source=reviewed_source,
            chunks=[second, first],
        )


def test_retrieval_request_is_bounded_deidentified_and_strict() -> None:
    request = GuidelineRetrievalRequest(
        clinical_query="  deidentified clinical question  ",
        top_k=8,
        publishers=[GuidelinePublisher.WHO, GuidelinePublisher.CDC],
        as_of=date(2026, 8, 3),
    )

    assert request.clinical_query == "deidentified clinical question"
    with pytest.raises(ValidationError, match="less than or equal to 8"):
        GuidelineRetrievalRequest(
            clinical_query="question",
            top_k=9,
            as_of=date(2026, 8, 3),
        )
    with pytest.raises(ValidationError, match="patient_id"):
        GuidelineRetrievalRequest.model_validate(
            {
                "clinical_query": "question",
                "as_of": "2026-08-03",
                "patient_id": "synthetic-patient-001",
            }
        )


def test_retrieval_match_enforces_source_chunk_and_citation_lineage() -> None:
    valid_match = match()

    with pytest.raises(ValidationError, match="citation chunk_id"):
        GuidelineRetrievalMatch.model_validate(
            {
                **valid_match.model_dump(mode="json"),
                "citation": {
                    **valid_match.citation.model_dump(mode="json"),
                    "chunk_id": "provider-controlled-id",
                },
            }
        )
    with pytest.raises(ValidationError, match="current and indexable"):
        GuidelineRetrievalMatch.model_validate(
            {
                **valid_match.model_dump(mode="json"),
                "source": source_values(
                    use_permission=GuidelineUsePermission.LINK_ONLY
                ),
            }
        )


def test_retrieval_result_supports_explicit_insufficient_evidence() -> None:
    result = GuidelineRetrievalResult(
        assessment=EvidenceAssessment.INSUFFICIENT,
        policy_version="guideline-retrieval-v1",
        query_fingerprint=QUERY_FINGERPRINT,
    )

    assert result.matches == []
    with pytest.raises(ValidationError, match="at least one match"):
        GuidelineRetrievalResult(
            assessment=EvidenceAssessment.SUFFICIENT,
            policy_version="guideline-retrieval-v1",
            query_fingerprint=QUERY_FINGERPRINT,
        )


def test_retrieval_result_requires_deterministic_ranks_and_unique_chunks() -> None:
    first = match(1)
    second = match(2)
    valid = GuidelineRetrievalResult(
        assessment=EvidenceAssessment.CONFLICTING,
        policy_version="guideline-retrieval-v1",
        query_fingerprint=QUERY_FINGERPRINT,
        matches=[first, second],
    )

    assert [item.rank for item in valid.matches] == [1, 2]
    with pytest.raises(ValidationError, match="ordered and contiguous"):
        GuidelineRetrievalResult(
            assessment=EvidenceAssessment.CONFLICTING,
            policy_version="guideline-retrieval-v1",
            query_fingerprint=QUERY_FINGERPRINT,
            matches=[second, first],
        )
    with pytest.raises(ValidationError, match="unique chunk IDs"):
        GuidelineRetrievalResult(
            assessment=EvidenceAssessment.CONFLICTING,
            policy_version="guideline-retrieval-v1",
            query_fingerprint=QUERY_FINGERPRINT,
            matches=[first, first.model_copy(update={"rank": 2})],
        )


def test_evidence_summary_removes_content_and_preserves_ranked_identity() -> None:
    result = GuidelineRetrievalResult(
        assessment=EvidenceAssessment.SUFFICIENT,
        policy_version="guideline-retrieval-v1",
        query_fingerprint=QUERY_FINGERPRINT,
        matches=[match()],
    )

    summary = GuidelineEvidenceSummary.from_retrieval_result(result)
    serialized = summary.model_dump(mode="json")

    assert serialized == {
        "assessment": "sufficient",
        "policy_version": "guideline-retrieval-v1",
        "query_fingerprint": QUERY_FINGERPRINT,
        "match_count": 1,
        "document_ids": ["who-guideline-2026-v1"],
        "chunk_ids": ["who-guideline-2026-v1.0"],
    }
    assert "Bounded synthetic text" not in str(serialized)
    assert "canonical_url" not in serialized


def test_evidence_summary_rejects_contradictory_counts_and_assessments() -> None:
    values = {
        "assessment": "sufficient",
        "policy_version": "guideline-retrieval-v1",
        "query_fingerprint": QUERY_FINGERPRINT,
        "match_count": 1,
        "document_ids": ["who-guideline-2026-v1"],
        "chunk_ids": ["who-guideline-2026-v1.0"],
    }

    with pytest.raises(ValidationError, match="match_count"):
        GuidelineEvidenceSummary.model_validate({**values, "match_count": 2})
    with pytest.raises(ValidationError, match="insufficient"):
        GuidelineEvidenceSummary.model_validate(
            {**values, "assessment": "insufficient"}
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        GuidelineEvidenceSummary.model_validate({**values, "provider": "weaviate"})


def test_provider_specific_fields_and_objects_are_rejected() -> None:
    with pytest.raises(ValidationError, match="_additional"):
        GuidelineRetrievalResult.model_validate(
            {
                "assessment": "insufficient",
                "policy_version": "guideline-retrieval-v1",
                "query_fingerprint": QUERY_FINGERPRINT,
                "_additional": {"distance": 0.1},
            }
        )

    class ProviderResult:
        assessment = "insufficient"

    with pytest.raises(ValidationError):
        GuidelineRetrievalResult.model_validate(ProviderResult())


def test_retrieval_failures_share_one_safe_application_base() -> None:
    failures = (
        GuidelineRetrievalTimeoutError("safe timeout"),
        GuidelineRetrievalUnavailableError("safe unavailable"),
        GuidelineRetrievalResponseError("safe malformed response"),
    )

    assert all(isinstance(failure, GuidelineRetrievalError) for failure in failures)
