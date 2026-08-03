"""Versioned Weaviate adapter for exact local guideline ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid5

from weaviate import WeaviateClient
from weaviate.classes.config import Configure, DataType, Property, VectorDistances
from weaviate.exceptions import WeaviateBaseError

from app.domain.guideline_index import (
    GuidelineIndexSnapshot,
    GuidelineIngestionResult,
    GuidelineVectorRecord,
)
from app.rag.vector_store import (
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreUnavailableError,
    GuidelineVectorStoreVerificationError,
    GuidelineVectorStoreWriteError,
)

GUIDELINE_COLLECTION = "ClinicalGuidelineChunkV1"
GUIDELINE_SCHEMA_VERSION = 1
GUIDELINE_OBJECT_NAMESPACE = UUID("740821e2-cf71-5a90-885d-e7bf4787d084")

GUIDELINE_PROPERTY_TYPES = {
    "schemaVersion": DataType.INT,
    "parserVersion": DataType.TEXT,
    "embeddingModel": DataType.TEXT,
    "embeddingDimensions": DataType.INT,
    "documentId": DataType.TEXT,
    "chunkId": DataType.TEXT,
    "title": DataType.TEXT,
    "publisher": DataType.TEXT,
    "sourceUrl": DataType.TEXT,
    "publicationDate": DataType.TEXT,
    "documentVersion": DataType.TEXT,
    "sourceSha256": DataType.TEXT,
    "lifecycleStatus": DataType.TEXT,
    "contentSha256": DataType.TEXT,
    "page": DataType.INT,
    "section": DataType.TEXT,
    "sequence": DataType.INT,
    "topics": DataType.TEXT_ARRAY,
    "text": DataType.TEXT,
}
_SEARCHABLE_PROPERTIES = {"title", "section", "text"}
GUIDELINE_FILTERABLE_PROPERTIES = {
    "schemaVersion",
    "parserVersion",
    "embeddingModel",
    "documentId",
    "chunkId",
    "publisher",
    "publicationDate",
    "sourceSha256",
    "lifecycleStatus",
    "contentSha256",
    "page",
    "sequence",
    "topics",
}


@dataclass(frozen=True)
class IngestionPlan:
    """Stable collection changes calculated before any mutation."""

    insert: tuple[UUID, ...]
    replace: tuple[UUID, ...]
    skip: tuple[UUID, ...]
    delete: tuple[UUID, ...]


def guideline_object_id(record_identity: str) -> UUID:
    """Create an application-owned stable UUID for a complete record identity."""

    return uuid5(GUIDELINE_OBJECT_NAMESPACE, record_identity)


def record_identity(
    *,
    parser_version: str,
    embedding_model: str,
    chunk_id: str,
    content_sha256: str,
) -> str:
    """Include every version that can change stored content or vectors."""

    return "|".join(
        (
            str(GUIDELINE_SCHEMA_VERSION),
            parser_version,
            embedding_model,
            chunk_id,
            content_sha256,
        )
    )


def record_properties(record: GuidelineVectorRecord) -> dict[str, object]:
    """Normalize a record into the only metadata accepted by the collection."""

    source = record.source
    chunk = record.chunk
    properties: dict[str, object] = {
        "schemaVersion": record.schema_version,
        "parserVersion": record.parser_version,
        "embeddingModel": record.embedding_model,
        "embeddingDimensions": record.embedding_dimensions,
        "documentId": source.document_id,
        "chunkId": chunk.chunk_id,
        "title": source.title,
        "publisher": source.publisher.value,
        "sourceUrl": str(source.canonical_url),
        "publicationDate": source.publication_date.isoformat(),
        "documentVersion": source.version,
        "sourceSha256": source.content_sha256,
        "lifecycleStatus": source.lifecycle_status.value,
        "contentSha256": chunk.content_sha256,
        "sequence": chunk.sequence,
        "topics": list(source.supported_topics),
        "text": chunk.text,
    }
    if chunk.page is not None:
        properties["page"] = chunk.page
    if chunk.section is not None:
        properties["section"] = chunk.section
    return properties


def plan_ingestion(
    expected: Mapping[UUID, Mapping[str, object]],
    existing: Mapping[UUID, Mapping[str, object]],
) -> IngestionPlan:
    """Plan deterministic exact replacement while preserving unrelated collections."""

    expected_ids = set(expected)
    existing_ids = set(existing)
    shared = expected_ids & existing_ids
    return IngestionPlan(
        insert=tuple(sorted(expected_ids - existing_ids, key=str)),
        replace=tuple(
            sorted(
                (
                    object_id
                    for object_id in shared
                    if expected[object_id] != existing[object_id]
                ),
                key=str,
            )
        ),
        skip=tuple(
            sorted(
                (
                    object_id
                    for object_id in shared
                    if expected[object_id] == existing[object_id]
                ),
                key=str,
            )
        ),
        delete=tuple(sorted(existing_ids - expected_ids, key=str)),
    )


def expected_snapshot(
    records: Sequence[GuidelineVectorRecord],
) -> GuidelineIndexSnapshot:
    """Validate corpus-wide invariants and derive its exact identity summary."""

    if not records:
        raise GuidelineVectorStoreVerificationError("guideline record set is empty")
    first = records[0]
    if any(record.schema_version != GUIDELINE_SCHEMA_VERSION for record in records):
        raise GuidelineVectorStoreVerificationError("record schema versions differ")
    if any(record.parser_version != first.parser_version for record in records):
        raise GuidelineVectorStoreVerificationError("record parser versions differ")
    if any(record.embedding_model != first.embedding_model for record in records):
        raise GuidelineVectorStoreVerificationError("embedding model IDs differ")
    if any(
        record.embedding_dimensions != first.embedding_dimensions for record in records
    ):
        raise GuidelineVectorStoreVerificationError("embedding dimensions differ")
    if len({record.object_id for record in records}) != len(records):
        raise GuidelineVectorStoreVerificationError("record object IDs are not unique")
    if len({record.chunk.chunk_id for record in records}) != len(records):
        raise GuidelineVectorStoreVerificationError("record chunk IDs are not unique")

    checksums: dict[str, str] = {}
    for record in records:
        previous = checksums.setdefault(
            record.source.document_id,
            record.source.content_sha256,
        )
        if previous != record.source.content_sha256:
            raise GuidelineVectorStoreVerificationError(
                "one document ID has conflicting source checksums"
            )
    return GuidelineIndexSnapshot(
        collection_name=GUIDELINE_COLLECTION,
        schema_version=GUIDELINE_SCHEMA_VERSION,
        embedding_model=first.embedding_model,
        embedding_dimensions=first.embedding_dimensions,
        document_count=len(checksums),
        chunk_count=len(records),
        source_checksums=dict(sorted(checksums.items())),
    )


class WeaviateGuidelineVectorStore:
    """Own exactly one self-vectorized Weaviate collection."""

    def __init__(self, client: WeaviateClient) -> None:
        self._client = client

    def sync(
        self,
        records: Sequence[GuidelineVectorRecord],
    ) -> GuidelineIngestionResult:
        snapshot = expected_snapshot(records)
        self._ensure_schema()
        collection = self._collection()
        expected = {record.object_id: record_properties(record) for record in records}
        record_by_id = {record.object_id: record for record in records}
        existing = self._read_existing()
        plan = plan_ingestion(expected, existing)

        try:
            for object_id in plan.insert:
                record = record_by_id[object_id]
                collection.data.insert(
                    uuid=object_id,
                    properties=expected[object_id],
                    vector=record.vector,
                )
            for object_id in plan.replace:
                record = record_by_id[object_id]
                collection.data.replace(
                    uuid=object_id,
                    properties=expected[object_id],
                    vector=record.vector,
                )
            # Stale objects are removed only after all expected writes succeed.
            for object_id in plan.delete:
                collection.data.delete_by_id(object_id)
        except WeaviateBaseError as error:
            raise GuidelineVectorStoreWriteError(
                "guideline collection mutation failed"
            ) from error

        verified = self.verify(records)
        if verified != snapshot:
            raise GuidelineVectorStoreVerificationError(
                "verified guideline snapshot changed unexpectedly"
            )
        return GuidelineIngestionResult(
            inserted=len(plan.insert),
            replaced=len(plan.replace),
            skipped=len(plan.skip),
            deleted=len(plan.delete),
            snapshot=verified,
        )

    def verify(
        self,
        records: Sequence[GuidelineVectorRecord],
    ) -> GuidelineIndexSnapshot:
        snapshot = expected_snapshot(records)
        self._ensure_schema()
        expected = {record.object_id: record_properties(record) for record in records}
        existing = self._read_existing()
        if set(existing) != set(expected):
            raise GuidelineVectorStoreVerificationError(
                "stored guideline object IDs do not match expected IDs"
            )
        if any(
            existing[object_id] != properties
            for object_id, properties in expected.items()
        ):
            raise GuidelineVectorStoreVerificationError(
                "stored guideline metadata does not match expected records"
            )
        return snapshot

    def reset(self) -> None:
        """Delete the fixed application collection and no other collection."""

        try:
            if self._client.collections.exists(GUIDELINE_COLLECTION):
                self._client.collections.delete(GUIDELINE_COLLECTION)
        except WeaviateBaseError as error:
            raise GuidelineVectorStoreWriteError(
                "guideline collection reset failed"
            ) from error

    def close(self) -> None:
        self._client.close()

    def _ensure_schema(self) -> None:
        try:
            if not self._client.collections.exists(GUIDELINE_COLLECTION):
                self._client.collections.create(
                    GUIDELINE_COLLECTION,
                    description=(
                        "Application-owned reviewed clinical guideline chunks; "
                        "schema version 1"
                    ),
                    properties=[
                        Property(
                            name=name,
                            data_type=data_type,
                            index_filterable=name in GUIDELINE_FILTERABLE_PROPERTIES,
                            index_searchable=name in _SEARCHABLE_PROPERTIES,
                            skip_vectorization=True,
                        )
                        for name, data_type in GUIDELINE_PROPERTY_TYPES.items()
                    ],
                    vector_config=Configure.Vectors.self_provided(
                        vector_index_config=Configure.VectorIndex.hnsw(
                            distance_metric=VectorDistances.COSINE
                        )
                    ),
                )
                return

            config = self._collection().config.get(simple=True)
            actual = {prop.name: prop.data_type for prop in config.properties}
            actual_filterable = {
                prop.name for prop in config.properties if prop.index_filterable
            }
            if (
                actual != GUIDELINE_PROPERTY_TYPES
                or actual_filterable != GUIDELINE_FILTERABLE_PROPERTIES
            ):
                raise GuidelineVectorStoreSchemaError(
                    "existing guideline collection schema is incompatible"
                )
            if config.vectorizer is not None:
                raise GuidelineVectorStoreSchemaError(
                    "guideline collection must use self-provided vectors"
                )
        except GuidelineVectorStoreSchemaError:
            raise
        except WeaviateBaseError as error:
            raise GuidelineVectorStoreUnavailableError(
                "could not inspect the guideline collection"
            ) from error

    def _collection(self) -> Any:
        return self._client.collections.get(GUIDELINE_COLLECTION)

    def _read_existing(self) -> dict[UUID, dict[str, object]]:
        try:
            objects = self._collection().iterator(include_vector=False)
            existing: dict[UUID, dict[str, object]] = {}
            for item in objects:
                object_id = UUID(str(item.uuid))
                if object_id in existing:
                    raise GuidelineVectorStoreVerificationError(
                        "duplicate object ID returned by guideline collection"
                    )
                existing[object_id] = cast(dict[str, object], dict(item.properties))
            return existing
        except GuidelineVectorStoreVerificationError:
            raise
        except (TypeError, ValueError, WeaviateBaseError) as error:
            raise GuidelineVectorStoreVerificationError(
                "could not normalize guideline collection objects"
            ) from error
