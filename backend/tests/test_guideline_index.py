"""Versioned guideline embedding and ingestion boundary tests."""

import json
import math
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from scripts.guideline_chunks import chunk_summary, write_processed_output
from scripts.guideline_index import build_records

from app.domain import (
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineSource,
    GuidelineUsePermission,
    GuidelineVectorCandidate,
    GuidelineVectorRecord,
    GuidelineVectorSearchRequest,
    ParsedGuidelineDocument,
)
from app.rag import (
    GuidelineEmbeddingResponseError,
    GuidelineVectorStoreVerificationError,
)
from app.services.deterministic_guideline_embeddings import (
    DETERMINISTIC_EMBEDDING_DIMENSIONS,
    DETERMINISTIC_EMBEDDING_MODEL,
    DeterministicGuidelineEmbeddingModel,
)
from app.services.pypdf_guidelines import PARSER_VERSION
from app.services.weaviate_guideline_index import (
    GUIDELINE_COLLECTION,
    GUIDELINE_SCHEMA_VERSION,
    WeaviateGuidelineVectorStore,
    expected_snapshot,
    guideline_object_id,
    plan_ingestion,
    record_identity,
    record_properties,
)


def parsed_document() -> ParsedGuidelineDocument:
    source = GuidelineSource(
        document_id="who-index-test",
        title="Synthetic guideline index fixture",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://example.test/who-index-test",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2026, 1, 1),
        version="test-v1",
        accessed_at=date(2026, 8, 3),
        license_name="Synthetic test permission",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 8, 3),
        license_review_note="Synthetic metadata and text only.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256=sha256(b"synthetic source").hexdigest(),
        supported_topics=["synthetic index"],
    )
    chunks = []
    for sequence, text in enumerate(
        ("Blood pressure guidance for adults.", "Synthetic metabolic guidance.")
    ):
        chunks.append(
            GuidelineChunk(
                chunk_id=f"who-index-test.p000{sequence + 1}.c000.0123456789ab",
                document_id=source.document_id,
                text=text,
                content_sha256=sha256(text.encode()).hexdigest(),
                sequence=sequence,
                page=sequence + 1,
                section="SYNTHETIC SECTION",
            )
        )
    return ParsedGuidelineDocument(
        parser_version=PARSER_VERSION,
        source=source,
        chunks=chunks,
    )


def vector_record() -> GuidelineVectorRecord:
    document = parsed_document()
    chunk = document.chunks[0]
    model = DeterministicGuidelineEmbeddingModel()
    vector = model.embed([chunk.text])[0]
    identity = record_identity(
        parser_version=document.parser_version,
        embedding_model=model.model_id,
        chunk_id=chunk.chunk_id,
        content_sha256=chunk.content_sha256,
    )
    return GuidelineVectorRecord(
        object_id=guideline_object_id(identity),
        schema_version=GUIDELINE_SCHEMA_VERSION,
        parser_version=document.parser_version,
        embedding_model=model.model_id,
        embedding_dimensions=model.dimensions,
        source=document.source,
        chunk=chunk,
        vector=list(vector),
    )


def test_deterministic_embeddings_are_bounded_finite_and_repeatable() -> None:
    model = DeterministicGuidelineEmbeddingModel()
    texts = ["Blood pressure in adults", "Metabolic clinical guidance"]

    first = model.embed(texts)
    second = model.embed(texts)

    assert first == second
    assert model.model_id == DETERMINISTIC_EMBEDDING_MODEL
    assert all(len(vector) == DETERMINISTIC_EMBEDDING_DIMENSIONS for vector in first)
    assert all(all(math.isfinite(value) for value in vector) for vector in first)
    assert all(
        math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)
        for vector in first
    )
    with pytest.raises(GuidelineEmbeddingResponseError, match="no tokens"):
        model.embed(["---"])


def test_vector_record_rejects_malformed_vectors_and_provider_fields() -> None:
    record = vector_record()
    values = record.model_dump(mode="json")

    with pytest.raises(ValidationError, match="vector length"):
        GuidelineVectorRecord.model_validate({**values, "vector": [1.0] * 8})
    with pytest.raises(ValidationError, match="finite"):
        GuidelineVectorRecord.model_validate(
            {**values, "vector": [float("nan")] * record.embedding_dimensions}
        )
    with pytest.raises(ValidationError, match="_additional"):
        GuidelineVectorRecord.model_validate({**values, "_additional": {}})


def test_stable_ids_include_parser_embedding_chunk_and_content_versions() -> None:
    base = {
        "parser_version": PARSER_VERSION,
        "embedding_model": DETERMINISTIC_EMBEDDING_MODEL,
        "chunk_id": "chunk-1",
        "content_sha256": sha256(b"one").hexdigest(),
    }
    first = guideline_object_id(record_identity(**base))

    assert first == guideline_object_id(record_identity(**base))
    for field, changed in (
        ("parser_version", "parser-v2"),
        ("embedding_model", "embedding-v2"),
        ("chunk_id", "chunk-2"),
        ("content_sha256", sha256(b"two").hexdigest()),
    ):
        assert guideline_object_id(record_identity(**{**base, field: changed})) != first


def test_ingestion_plan_is_idempotent_and_replaces_changed_records() -> None:
    inserted_id = UUID("00000000-0000-0000-0000-000000000001")
    changed_id = UUID("00000000-0000-0000-0000-000000000002")
    skipped_id = UUID("00000000-0000-0000-0000-000000000003")
    stale_id = UUID("00000000-0000-0000-0000-000000000004")
    expected = {
        inserted_id: {"text": "new"},
        changed_id: {"text": "replacement"},
        skipped_id: {"text": "same"},
    }
    existing = {
        changed_id: {"text": "old"},
        skipped_id: {"text": "same"},
        stale_id: {"text": "stale"},
    }

    plan = plan_ingestion(expected, existing)

    assert plan.insert == (inserted_id,)
    assert plan.replace == (changed_id,)
    assert plan.skip == (skipped_id,)
    assert plan.delete == (stale_id,)
    idempotent = plan_ingestion(expected, expected)
    assert idempotent.skip == tuple(expected)
    assert not idempotent.insert and not idempotent.replace and not idempotent.delete


def test_snapshot_and_properties_have_exact_content_identity_without_patient_data() -> (
    None
):
    record = vector_record()
    snapshot = expected_snapshot([record])
    properties = record_properties(record)

    assert snapshot.collection_name == GUIDELINE_COLLECTION
    assert snapshot.document_count == 1
    assert snapshot.chunk_count == 1
    assert snapshot.source_checksums == {
        record.source.document_id: record.source.content_sha256
    }
    serialized = json.dumps(properties)
    assert set(properties) == {
        "schemaVersion",
        "parserVersion",
        "embeddingModel",
        "embeddingDimensions",
        "documentId",
        "chunkId",
        "title",
        "publisher",
        "sourceUrl",
        "publicationDate",
        "documentVersion",
        "sourceSha256",
        "lifecycleStatus",
        "contentSha256",
        "page",
        "section",
        "sequence",
        "topics",
        "text",
    }
    assert "patient_id" not in serialized and "patient_summary" not in serialized


def test_record_builder_requires_chunk_lock_and_is_repeatable(tmp_path: Path) -> None:
    document = parsed_document()
    input_path = tmp_path / "chunks.json"
    lock_path = tmp_path / "chunk-lock.json"
    write_processed_output([document], input_path)
    lock_path.write_text(json.dumps(chunk_summary([document])), encoding="utf-8")
    model = DeterministicGuidelineEmbeddingModel()

    first = build_records(input_path, lock_path, model)
    second = build_records(input_path, lock_path, model)

    assert first == second
    assert len(first) == 2
    assert len({record.object_id for record in first}) == 2


def test_empty_or_duplicate_record_sets_fail_before_store_mutation() -> None:
    with pytest.raises(GuidelineVectorStoreVerificationError, match="empty"):
        expected_snapshot([])
    record = vector_record()
    with pytest.raises(GuidelineVectorStoreVerificationError, match="not unique"):
        expected_snapshot([record, record])


def test_reset_targets_only_fixed_application_collection() -> None:
    client = MagicMock()
    client.collections.exists.return_value = True
    store = WeaviateGuidelineVectorStore(cast(Any, client))

    store.reset()

    client.collections.exists.assert_called_once_with(GUIDELINE_COLLECTION)
    client.collections.delete.assert_called_once_with(GUIDELINE_COLLECTION)
    client.collections.create.assert_not_called()


def test_vector_search_request_is_bounded_finite_and_deidentified() -> None:
    model = DeterministicGuidelineEmbeddingModel()
    vector = list(model.embed(["adult blood pressure guidance"])[0])
    request = GuidelineVectorSearchRequest(
        schema_version=GUIDELINE_SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        embedding_model=model.model_id,
        embedding_dimensions=model.dimensions,
        vector=vector,
        eligible_document_ids=["who-hypertension-2021"],
        candidate_limit=32,
    )

    assert request.candidate_limit == 32
    with pytest.raises(ValidationError, match="eligible_document_ids must be unique"):
        GuidelineVectorSearchRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "eligible_document_ids": [
                    "who-hypertension-2021",
                    "who-hypertension-2021",
                ],
            }
        )
    with pytest.raises(ValidationError, match="patient_id"):
        GuidelineVectorSearchRequest.model_validate(
            {**request.model_dump(mode="json"), "patient_id": "synthetic-001"}
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("vector", [0.0] * DETERMINISTIC_EMBEDDING_DIMENSIONS, "all zero"),
        ("vector", [1.0] * 8, "vector length"),
        ("candidate_limit", 33, "less than or equal to 32"),
    ],
)
def test_vector_search_request_rejects_malformed_bounds(
    field: str,
    value: object,
    message: str,
) -> None:
    model = DeterministicGuidelineEmbeddingModel()
    values: dict[str, object] = {
        "schema_version": GUIDELINE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "embedding_model": model.model_id,
        "embedding_dimensions": model.dimensions,
        "vector": list(model.embed(["diabetes guidance"])[0]),
        "eligible_document_ids": ["who-hearts-d-2020"],
        "candidate_limit": 8,
    }
    values[field] = value

    with pytest.raises(ValidationError, match=message):
        GuidelineVectorSearchRequest.model_validate(values)


def test_vector_candidate_keeps_provider_data_outside_trusted_source() -> None:
    record = vector_record()
    candidate = GuidelineVectorCandidate(
        object_id=record.object_id,
        schema_version=record.schema_version,
        parser_version=record.parser_version,
        embedding_model=record.embedding_model,
        embedding_dimensions=record.embedding_dimensions,
        source_sha256=record.source.content_sha256,
        document_version=record.source.version,
        publisher=record.source.publisher,
        publication_date=record.source.publication_date,
        lifecycle_status=record.source.lifecycle_status,
        chunk=record.chunk,
        distance=0.25,
    )

    assert candidate.chunk.document_id == record.source.document_id
    assert "source" not in candidate.model_fields_set
    with pytest.raises(ValidationError, match="less than or equal to 2"):
        GuidelineVectorCandidate.model_validate(
            {**candidate.model_dump(mode="json"), "distance": 2.1}
        )
    with pytest.raises(ValidationError, match="_additional"):
        GuidelineVectorCandidate.model_validate(
            {**candidate.model_dump(mode="json"), "_additional": {"score": 0.9}}
        )
