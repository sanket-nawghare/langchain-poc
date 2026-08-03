"""Provider-neutral contracts for the local clinical-guideline index."""

import math
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.domain.base import ContractModel
from app.domain.guidelines import (
    GuidelineChunk,
    GuidelineIdentifier,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineSource,
    Sha256Digest,
    ShortMetadata,
)

EmbeddingModelId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
CollectionName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Za-z0-9]*$",
    ),
]


class GuidelineVectorRecord(ContractModel):
    """One source-owned chunk and its application-generated vector."""

    object_id: UUID
    schema_version: int = Field(ge=1, le=100)
    parser_version: str = Field(min_length=1, max_length=160)
    embedding_model: EmbeddingModelId
    embedding_dimensions: int = Field(ge=8, le=4096)
    source: GuidelineSource
    chunk: GuidelineChunk
    vector: list[float] = Field(min_length=8, max_length=4096)

    @model_validator(mode="after")
    def validate_record(self) -> "GuidelineVectorRecord":
        if self.chunk.document_id != self.source.document_id:
            raise ValueError("chunk document_id must match source document_id")
        if not self.source.is_indexable:
            raise ValueError("vector source must be current and indexable")
        if len(self.vector) != self.embedding_dimensions:
            raise ValueError("vector length must match embedding_dimensions")
        if not all(math.isfinite(value) for value in self.vector):
            raise ValueError("vector values must be finite")
        if not any(value != 0 for value in self.vector):
            raise ValueError("vector must not be all zero")
        return self


class GuidelineIndexSnapshot(ContractModel):
    """Verified content identity for one complete application collection."""

    collection_name: CollectionName
    schema_version: int = Field(ge=1, le=100)
    embedding_model: EmbeddingModelId
    embedding_dimensions: int = Field(ge=8, le=4096)
    document_count: int = Field(ge=0, le=8)
    chunk_count: int = Field(ge=0, le=8000)
    source_checksums: dict[str, Sha256Digest] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_counts(self) -> "GuidelineIndexSnapshot":
        if len(self.source_checksums) != self.document_count:
            raise ValueError("source checksum count must match document_count")
        if self.document_count == 0 and self.chunk_count != 0:
            raise ValueError("empty document set must have no chunks")
        return self


class GuidelineIngestionResult(ContractModel):
    """Deterministic mutation summary returned after exact verification."""

    inserted: int = Field(ge=0)
    replaced: int = Field(ge=0)
    skipped: int = Field(ge=0)
    deleted: int = Field(ge=0)
    snapshot: GuidelineIndexSnapshot

    @model_validator(mode="after")
    def validate_ingested_count(self) -> "GuidelineIngestionResult":
        if self.inserted + self.replaced + self.skipped != self.snapshot.chunk_count:
            raise ValueError("ingestion actions must account for every expected chunk")
        return self


class GuidelineVectorSearchRequest(ContractModel):
    """Bounded provider-neutral candidate query over an eligible source set."""

    schema_version: int = Field(ge=1, le=100)
    parser_version: ShortMetadata
    embedding_model: EmbeddingModelId
    embedding_dimensions: int = Field(ge=8, le=4096)
    vector: list[float] = Field(min_length=8, max_length=4096)
    eligible_document_ids: list[GuidelineIdentifier] = Field(
        min_length=1,
        max_length=8,
    )
    candidate_limit: int = Field(ge=1, le=32)

    @model_validator(mode="after")
    def validate_query(self) -> "GuidelineVectorSearchRequest":
        if len(self.vector) != self.embedding_dimensions:
            raise ValueError("vector length must match embedding_dimensions")
        if not all(math.isfinite(value) for value in self.vector):
            raise ValueError("vector values must be finite")
        if not any(value != 0 for value in self.vector):
            raise ValueError("vector must not be all zero")
        if len(set(self.eligible_document_ids)) != len(self.eligible_document_ids):
            raise ValueError("eligible_document_ids must be unique")
        return self


class GuidelineVectorCandidate(ContractModel):
    """Normalized untrusted vector candidate awaiting trusted-source hydration."""

    object_id: UUID
    schema_version: int = Field(ge=1, le=100)
    parser_version: ShortMetadata
    embedding_model: EmbeddingModelId
    embedding_dimensions: int = Field(ge=8, le=4096)
    source_sha256: Sha256Digest
    document_version: ShortMetadata
    publisher: GuidelinePublisher
    publication_date: date
    lifecycle_status: GuidelineLifecycleStatus
    chunk: GuidelineChunk
    distance: float = Field(ge=0, le=2)

    @model_validator(mode="after")
    def validate_candidate(self) -> "GuidelineVectorCandidate":
        if not math.isfinite(self.distance):
            raise ValueError("distance must be finite")
        return self
