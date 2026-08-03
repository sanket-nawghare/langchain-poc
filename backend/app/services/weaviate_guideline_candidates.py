"""Filtered asynchronous Weaviate candidate search and strict normalization."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from weaviate import WeaviateAsyncClient
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.exceptions import WeaviateBaseError, WeaviateTimeoutError

from app.domain.guideline_index import (
    GuidelineVectorCandidate,
    GuidelineVectorSearchRequest,
)
from app.domain.guidelines import GuidelineChunk
from app.rag.vector_store import (
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
    GuidelineVectorStoreVerificationError,
)
from app.services.weaviate_guideline_index import (
    GUIDELINE_COLLECTION,
    GUIDELINE_FILTERABLE_PROPERTIES,
    GUIDELINE_PROPERTY_TYPES,
    GUIDELINE_SCHEMA_VERSION,
    guideline_object_id,
    record_identity,
)

_RETURN_PROPERTIES = (
    "schemaVersion",
    "parserVersion",
    "embeddingModel",
    "embeddingDimensions",
    "documentId",
    "chunkId",
    "publisher",
    "publicationDate",
    "documentVersion",
    "sourceSha256",
    "lifecycleStatus",
    "contentSha256",
    "page",
    "section",
    "sequence",
    "text",
)
_REQUIRED_PROPERTIES = set(_RETURN_PROPERTIES) - {"page", "section"}
_OPTIONAL_PROPERTIES = {"page", "section"}


class WeaviateGuidelineCandidateStore:
    """Query one fixed collection without trusting provider source metadata."""

    def __init__(
        self,
        client: WeaviateAsyncClient,
        *,
        parser_version: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        self._client = client
        self._parser_version = parser_version
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions

    async def search(
        self,
        request: GuidelineVectorSearchRequest,
    ) -> tuple[GuidelineVectorCandidate, ...]:
        self._validate_request_identity(request)
        collection = await self._validated_collection()
        filters = Filter.all_of(
            [
                Filter.by_property("schemaVersion").equal(request.schema_version),
                Filter.by_property("parserVersion").equal(request.parser_version),
                Filter.by_property("embeddingModel").equal(request.embedding_model),
                Filter.by_property("lifecycleStatus").equal("current"),
                Filter.any_of(
                    [
                        Filter.by_property("documentId").equal(document_id)
                        for document_id in request.eligible_document_ids
                    ]
                ),
            ]
        )
        try:
            response = await collection.query.near_vector(
                near_vector=request.vector,
                limit=request.candidate_limit,
                filters=filters,
                return_properties=list(_RETURN_PROPERTIES),
                return_metadata=MetadataQuery(distance=True),
            )
        except WeaviateTimeoutError as error:
            raise GuidelineVectorStoreTimeoutError(
                "guideline candidate query timed out"
            ) from error
        except WeaviateBaseError as error:
            raise GuidelineVectorStoreUnavailableError(
                "guideline candidate query is unavailable"
            ) from error

        candidates = tuple(self._normalize(item) for item in response.objects)
        eligible_ids = set(request.eligible_document_ids)
        for candidate in candidates:
            if (
                candidate.schema_version != request.schema_version
                or candidate.parser_version != request.parser_version
                or candidate.embedding_model != request.embedding_model
                or candidate.embedding_dimensions != request.embedding_dimensions
                or candidate.lifecycle_status.value != "current"
                or candidate.chunk.document_id not in eligible_ids
            ):
                raise GuidelineVectorStoreVerificationError(
                    "guideline candidate identity does not match query"
                )
            text_sha256 = hashlib.sha256(
                candidate.chunk.text.encode("utf-8")
            ).hexdigest()
            expected_id = guideline_object_id(
                record_identity(
                    parser_version=candidate.parser_version,
                    embedding_model=candidate.embedding_model,
                    chunk_id=candidate.chunk.chunk_id,
                    content_sha256=candidate.chunk.content_sha256,
                )
            )
            if (
                text_sha256 != candidate.chunk.content_sha256
                or expected_id != candidate.object_id
            ):
                raise GuidelineVectorStoreVerificationError(
                    "guideline candidate content identity is invalid"
                )
        object_ids = [candidate.object_id for candidate in candidates]
        chunk_ids = [candidate.chunk.chunk_id for candidate in candidates]
        if len(set(object_ids)) != len(object_ids) or len(set(chunk_ids)) != len(
            chunk_ids
        ):
            raise GuidelineVectorStoreVerificationError(
                "guideline candidate response contains duplicate identities"
            )
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.distance,
                    candidate.chunk.chunk_id,
                    str(candidate.object_id),
                ),
            )
        )

    async def close(self) -> None:
        await self._client.close()

    def _validate_request_identity(
        self,
        request: GuidelineVectorSearchRequest,
    ) -> None:
        if (
            request.schema_version != GUIDELINE_SCHEMA_VERSION
            or request.parser_version != self._parser_version
            or request.embedding_model != self._embedding_model
            or request.embedding_dimensions != self._embedding_dimensions
        ):
            raise GuidelineVectorStoreSchemaError(
                "guideline candidate query identity is incompatible"
            )

    async def _validated_collection(self) -> Any:
        try:
            if not await self._client.collections.exists(GUIDELINE_COLLECTION):
                raise GuidelineVectorStoreSchemaError(
                    "guideline candidate collection is missing"
                )
            collection = self._client.collections.get(GUIDELINE_COLLECTION)
            config = await collection.config.get(simple=True)
            actual = {prop.name: prop.data_type for prop in config.properties}
            actual_filterable = {
                prop.name for prop in config.properties if prop.index_filterable
            }
            if (
                actual != GUIDELINE_PROPERTY_TYPES
                or actual_filterable != GUIDELINE_FILTERABLE_PROPERTIES
                or config.vectorizer is not None
            ):
                raise GuidelineVectorStoreSchemaError(
                    "guideline candidate collection schema is incompatible"
                )
            return collection
        except GuidelineVectorStoreSchemaError:
            raise
        except WeaviateTimeoutError as error:
            raise GuidelineVectorStoreTimeoutError(
                "guideline candidate schema check timed out"
            ) from error
        except WeaviateBaseError as error:
            raise GuidelineVectorStoreUnavailableError(
                "guideline candidate schema is unavailable"
            ) from error

    def _normalize(self, item: Any) -> GuidelineVectorCandidate:
        try:
            properties = dict(item.properties)
            keys = set(properties)
            if not _REQUIRED_PROPERTIES.issubset(keys) or not keys.issubset(
                _REQUIRED_PROPERTIES | _OPTIONAL_PROPERTIES
            ):
                raise ValueError("candidate properties do not match contract")
            distance = item.metadata.distance
            if distance is None:
                raise ValueError("candidate distance is missing")
            chunk = GuidelineChunk(
                chunk_id=properties["chunkId"],
                document_id=properties["documentId"],
                text=properties["text"],
                content_sha256=properties["contentSha256"],
                sequence=properties["sequence"],
                page=properties.get("page"),
                section=properties.get("section"),
            )
            return GuidelineVectorCandidate(
                object_id=UUID(str(item.uuid)),
                schema_version=properties["schemaVersion"],
                parser_version=properties["parserVersion"],
                embedding_model=properties["embeddingModel"],
                embedding_dimensions=properties["embeddingDimensions"],
                source_sha256=properties["sourceSha256"],
                document_version=properties["documentVersion"],
                publisher=properties["publisher"],
                publication_date=properties["publicationDate"],
                lifecycle_status=properties["lifecycleStatus"],
                chunk=chunk,
                distance=distance,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise GuidelineVectorStoreVerificationError(
                "guideline candidate response is malformed"
            ) from error
