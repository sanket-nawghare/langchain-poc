"""Trusted source catalog and filtered Weaviate candidate adapter tests."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from weaviate.exceptions import WeaviateTimeoutError

from app.domain import (
    GuidelineChunk,
    GuidelinePublisher,
    GuidelineRetrievalRequest,
    GuidelineVectorCandidate,
    GuidelineVectorSearchRequest,
)
from app.rag import (
    GuidelineRetrievalResponseError,
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreVerificationError,
    eligible_guideline_sources,
    trusted_source_for_candidate,
)
from app.services.deterministic_guideline_embeddings import (
    DETERMINISTIC_EMBEDDING_DIMENSIONS,
    DETERMINISTIC_EMBEDDING_MODEL,
    DeterministicGuidelineEmbeddingModel,
)
from app.services.guideline_source_catalog import LockedGuidelineSourceCatalog
from app.services.weaviate_guideline_candidates import (
    WeaviateGuidelineCandidateStore,
)
from app.services.weaviate_guideline_index import (
    GUIDELINE_COLLECTION,
    GUIDELINE_FILTERABLE_PROPERTIES,
    GUIDELINE_PROPERTY_TYPES,
    GUIDELINE_SCHEMA_VERSION,
    guideline_object_id,
    record_identity,
)

SOURCE_CHECKSUM = sha256(b"reviewed source").hexdigest()
CHUNK_TEXT = "Synthetic adult blood pressure target guidance."
CHUNK_CHECKSUM = sha256(CHUNK_TEXT.encode()).hexdigest()
PARSER_VERSION = "deterministic-pypdf-v1"


def source_values(
    document_id: str = "who-hypertension-2021",
    *,
    publisher: str = "who",
    publication_date: str = "2021-08-24",
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "title": f"Reviewed {document_id}",
        "publisher": publisher,
        "canonical_url": f"https://example.test/{document_id}",
        "document_format": "pdf",
        "publication_date": publication_date,
        "version": "version-1",
        "accessed_at": "2026-08-03",
        "license_name": "Reviewed test license",
        "license_url": "https://example.test/license",
        "use_permission": "local_index_only",
        "license_reviewed_at": "2026-08-03",
        "license_review_note": "Synthetic source metadata for tests.",
        "lifecycle_status": "current",
        "content_sha256": SOURCE_CHECKSUM,
        "supported_topics": ["adult hypertension"],
        "language": "en",
    }


def write_catalog(path: Path, *, extra_field: bool = False) -> None:
    documents = []
    for source in (
        source_values(),
        source_values(
            "cdc-hypertension-2024",
            publisher="cdc",
            publication_date="2024-01-01",
        ),
    ):
        document: dict[str, object] = {
            "source": source,
            "artifact": {
                "download_url": "https://example.test/document.pdf",
                "filename": f"{source['document_id']}.pdf",
                "page_count": 1,
                "size_bytes": 100,
            },
            "supported_scenarios": ["synthetic-scenario"],
        }
        documents.append(document)
    if extra_field:
        documents[0]["provider"] = {"trusted": False}
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "content": "reviewed-guideline-provenance-and-checksums-only",
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )


def candidate_properties(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schemaVersion": GUIDELINE_SCHEMA_VERSION,
        "parserVersion": PARSER_VERSION,
        "embeddingModel": DETERMINISTIC_EMBEDDING_MODEL,
        "embeddingDimensions": DETERMINISTIC_EMBEDDING_DIMENSIONS,
        "documentId": "who-hypertension-2021",
        "chunkId": "who-hypertension-2021.p0012.c000.0123456789ab",
        "publisher": "who",
        "publicationDate": "2021-08-24",
        "documentVersion": "version-1",
        "sourceSha256": SOURCE_CHECKSUM,
        "lifecycleStatus": "current",
        "contentSha256": CHUNK_CHECKSUM,
        "page": 12,
        "section": "BLOOD PRESSURE TARGETS",
        "sequence": 17,
        "text": CHUNK_TEXT,
    }
    values.update(overrides)
    return values


def search_request() -> GuidelineVectorSearchRequest:
    model = DeterministicGuidelineEmbeddingModel()
    return GuidelineVectorSearchRequest(
        schema_version=GUIDELINE_SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        embedding_model=model.model_id,
        embedding_dimensions=model.dimensions,
        vector=list(model.embed(["adult blood pressure targets"])[0]),
        eligible_document_ids=["who-hypertension-2021"],
        candidate_limit=8,
    )


def candidate(**overrides: object) -> GuidelineVectorCandidate:
    properties = candidate_properties(**overrides)
    return GuidelineVectorCandidate(
        object_id=guideline_object_id(
            record_identity(
                parser_version=str(properties["parserVersion"]),
                embedding_model=str(properties["embeddingModel"]),
                chunk_id=str(properties["chunkId"]),
                content_sha256=str(properties["contentSha256"]),
            )
        ),
        schema_version=properties["schemaVersion"],
        parser_version=properties["parserVersion"],
        embedding_model=properties["embeddingModel"],
        embedding_dimensions=properties["embeddingDimensions"],
        source_sha256=properties["sourceSha256"],
        document_version=properties["documentVersion"],
        publisher=properties["publisher"],
        publication_date=properties["publicationDate"],
        lifecycle_status=properties["lifecycleStatus"],
        chunk=GuidelineChunk(
            chunk_id=properties["chunkId"],
            document_id=properties["documentId"],
            text=properties["text"],
            content_sha256=properties["contentSha256"],
            sequence=properties["sequence"],
            page=properties["page"],
            section=properties["section"],
        ),
        distance=0.2,
    )


def fake_client(*items: object, collection_exists: bool = True) -> Any:
    config = SimpleNamespace(
        properties=[
            SimpleNamespace(
                name=name,
                data_type=data_type,
                index_filterable=name in GUIDELINE_FILTERABLE_PROPERTIES,
            )
            for name, data_type in GUIDELINE_PROPERTY_TYPES.items()
        ],
        vectorizer=None,
    )
    collection = SimpleNamespace(
        config=SimpleNamespace(get=AsyncMock(return_value=config)),
        query=SimpleNamespace(
            near_vector=AsyncMock(
                return_value=SimpleNamespace(objects=list(items)),
            )
        ),
    )
    collections = SimpleNamespace(
        exists=AsyncMock(return_value=collection_exists),
        get=MagicMock(return_value=collection),
    )
    return SimpleNamespace(collections=collections, close=AsyncMock())


def provider_item(
    *,
    object_id: UUID | None = None,
    distance: float | None = 0.2,
    properties: dict[str, object] | None = None,
) -> object:
    return SimpleNamespace(
        uuid=object_id
        or guideline_object_id(
            record_identity(
                parser_version=str(
                    (properties or candidate_properties())["parserVersion"]
                ),
                embedding_model=str(
                    (properties or candidate_properties())["embeddingModel"]
                ),
                chunk_id=str((properties or candidate_properties())["chunkId"]),
                content_sha256=str(
                    (properties or candidate_properties())["contentSha256"]
                ),
            )
        ),
        properties=properties or candidate_properties(),
        metadata=SimpleNamespace(distance=distance),
        provider_payload={"must_not_cross": True},
    )


def test_locked_catalog_is_strict_and_sorted(tmp_path: Path) -> None:
    path = tmp_path / "corpus-lock.json"
    write_catalog(path)

    catalog = LockedGuidelineSourceCatalog(path)

    assert [source.document_id for source in catalog.sources()] == [
        "cdc-hypertension-2024",
        "who-hypertension-2021",
    ]
    write_catalog(path, extra_field=True)
    with pytest.raises(GuidelineRetrievalResponseError, match="unexpected"):
        LockedGuidelineSourceCatalog(path)


def test_eligibility_uses_trusted_as_of_and_publisher_filters(tmp_path: Path) -> None:
    path = tmp_path / "corpus-lock.json"
    write_catalog(path)
    catalog = LockedGuidelineSourceCatalog(path)

    as_of_2022 = GuidelineRetrievalRequest(
        clinical_query="adult blood pressure target",
        as_of=date(2022, 1, 1),
    )
    assert [
        source.document_id for source in eligible_guideline_sources(catalog, as_of_2022)
    ] == ["who-hypertension-2021"]
    cdc_only = GuidelineRetrievalRequest(
        clinical_query="adult blood pressure target",
        as_of=date(2026, 1, 1),
        publishers=[GuidelinePublisher.CDC],
    )
    assert [
        source.document_id for source in eligible_guideline_sources(catalog, cdc_only)
    ] == ["cdc-hypertension-2024"]


def test_candidate_source_must_match_trusted_catalog(tmp_path: Path) -> None:
    path = tmp_path / "corpus-lock.json"
    write_catalog(path)
    source = LockedGuidelineSourceCatalog(path).sources()[1]

    assert (
        trusted_source_for_candidate(candidate(), {source.document_id: source})
        == source
    )
    with pytest.raises(GuidelineRetrievalResponseError, match="does not match"):
        trusted_source_for_candidate(
            candidate(sourceSha256=sha256(b"drift").hexdigest()),
            {source.document_id: source},
        )


@pytest.mark.anyio
async def test_adapter_applies_exact_filters_and_normalizes_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePropertyFilter:
        def __init__(self, name: str) -> None:
            self.name = name

        def equal(self, value: object) -> tuple[str, str, object]:
            return ("equal", self.name, value)

    class FakeFilter:
        @staticmethod
        def by_property(name: str) -> FakePropertyFilter:
            return FakePropertyFilter(name)

        @staticmethod
        def all_of(filters: list[object]) -> tuple[str, list[object]]:
            return ("all", filters)

        @staticmethod
        def any_of(filters: list[object]) -> tuple[str, list[object]]:
            return ("any", filters)

    monkeypatch.setattr(
        "app.services.weaviate_guideline_candidates.Filter",
        FakeFilter,
    )
    client = fake_client(provider_item())
    store = WeaviateGuidelineCandidateStore(
        cast(Any, client),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )

    result = await store.search(search_request())

    assert len(result) == 1
    assert result[0].chunk.chunk_id == candidate_properties()["chunkId"]
    assert not hasattr(result[0], "provider_payload")
    client.collections.exists.assert_awaited_once_with(GUIDELINE_COLLECTION)
    kwargs = client.collections.get.return_value.query.near_vector.await_args.kwargs
    assert kwargs["limit"] == 8
    assert kwargs["filters"] == (
        "all",
        [
            ("equal", "schemaVersion", 1),
            ("equal", "parserVersion", PARSER_VERSION),
            ("equal", "embeddingModel", DETERMINISTIC_EMBEDDING_MODEL),
            ("equal", "lifecycleStatus", "current"),
            ("any", [("equal", "documentId", "who-hypertension-2021")]),
        ],
    )


@pytest.mark.anyio
async def test_adapter_rejects_schema_provider_and_duplicate_drift() -> None:
    missing_client = fake_client(collection_exists=False)
    missing_store = WeaviateGuidelineCandidateStore(
        cast(Any, missing_client),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )
    with pytest.raises(GuidelineVectorStoreSchemaError, match="missing"):
        await missing_store.search(search_request())

    extra = candidate_properties(providerScore=0.99)
    malformed_store = WeaviateGuidelineCandidateStore(
        cast(Any, fake_client(provider_item(properties=extra))),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )
    with pytest.raises(GuidelineVectorStoreVerificationError, match="malformed"):
        await malformed_store.search(search_request())

    duplicate_store = WeaviateGuidelineCandidateStore(
        cast(Any, fake_client(provider_item(), provider_item())),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )
    with pytest.raises(GuidelineVectorStoreVerificationError, match="duplicate"):
        await duplicate_store.search(search_request())

    identity_store = WeaviateGuidelineCandidateStore(
        cast(
            Any,
            fake_client(
                provider_item(
                    properties=candidate_properties(
                        documentId="who-untrusted-document",
                    )
                )
            ),
        ),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )
    with pytest.raises(GuidelineVectorStoreVerificationError, match="query"):
        await identity_store.search(search_request())

    content_store = WeaviateGuidelineCandidateStore(
        cast(
            Any,
            fake_client(
                provider_item(
                    properties=candidate_properties(
                        text="Provider-tampered text with the old checksum.",
                    )
                )
            ),
        ),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )
    with pytest.raises(GuidelineVectorStoreVerificationError, match="content"):
        await content_store.search(search_request())


@pytest.mark.anyio
async def test_adapter_maps_query_timeout_and_closes_client() -> None:
    client = fake_client()
    client.collections.get.return_value.query.near_vector.side_effect = (
        WeaviateTimeoutError("bounded timeout")
    )
    store = WeaviateGuidelineCandidateStore(
        cast(Any, client),
        parser_version=PARSER_VERSION,
        embedding_model=DETERMINISTIC_EMBEDDING_MODEL,
        embedding_dimensions=DETERMINISTIC_EMBEDDING_DIMENSIONS,
    )

    with pytest.raises(GuidelineVectorStoreTimeoutError, match="timed out"):
        await store.search(search_request())
    await store.close()
    client.close.assert_awaited_once()
