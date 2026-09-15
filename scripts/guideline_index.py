"""Build, sync, verify, or reset the versioned local guideline index."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import weaviate
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.exceptions import WeaviateBaseError

from app.core.config import Settings
from app.domain.guideline_index import GuidelineVectorRecord
from app.rag.embeddings import GuidelineEmbeddingError, GuidelineEmbeddingModel
from app.rag.vector_store import GuidelineVectorStoreError
from app.services.deterministic_guideline_embeddings import (
    MAX_EMBEDDING_BATCH,
    DeterministicGuidelineEmbeddingModel,
)
from app.services.weaviate_guideline_index import (
    GUIDELINE_COLLECTION,
    GUIDELINE_SCHEMA_VERSION,
    WeaviateGuidelineVectorStore,
    guideline_object_id,
    record_identity,
)
from scripts.guideline_chunks import (
    GuidelineChunkBuildError,
    chunk_summary,
    load_processed_output,
    verify_chunk_lock,
)


class GuidelineIndexCommandError(RuntimeError):
    """Safe local index command failure."""


def build_records(
    input_path: Path,
    chunk_lock_path: Path,
    embedding_model: GuidelineEmbeddingModel,
) -> tuple[GuidelineVectorRecord, ...]:
    """Strictly verify local chunks and build deterministic vector records."""

    documents = load_processed_output(input_path)
    verify_chunk_lock(chunk_summary(documents), chunk_lock_path)
    pairs = tuple(
        (document, chunk) for document in documents for chunk in document.chunks
    )
    vectors: list[tuple[float, ...]] = []
    for offset in range(0, len(pairs), MAX_EMBEDDING_BATCH):
        batch = pairs[offset : offset + MAX_EMBEDDING_BATCH]
        vectors.extend(embedding_model.embed([chunk.text for _, chunk in batch]))
    if len(vectors) != len(pairs):
        raise GuidelineIndexCommandError(
            "embedding output count does not match guideline chunk count"
        )

    return tuple(
        GuidelineVectorRecord(
            object_id=guideline_object_id(
                record_identity(
                    parser_version=document.parser_version,
                    embedding_model=embedding_model.model_id,
                    chunk_id=chunk.chunk_id,
                    content_sha256=chunk.content_sha256,
                )
            ),
            schema_version=GUIDELINE_SCHEMA_VERSION,
            parser_version=document.parser_version,
            embedding_model=embedding_model.model_id,
            embedding_dimensions=embedding_model.dimensions,
            source=document.source,
            chunk=chunk,
            vector=list(vector),
        )
        for (document, chunk), vector in zip(pairs, vectors, strict=True)
    )


def _local_connection(settings: Settings) -> weaviate.WeaviateClient:
    parsed = urlsplit(str(settings.weaviate_url))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise GuidelineIndexCommandError(
            "guideline index commands require a loopback-only HTTP Weaviate URL"
        )
    if parsed.hostname is None:
        raise GuidelineIndexCommandError("Weaviate URL has no host")
    return weaviate.connect_to_custom(
        http_host=parsed.hostname,
        http_port=parsed.port or 80,
        http_secure=False,
        grpc_host=parsed.hostname,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=False,
        additional_config=AdditionalConfig(
            timeout=Timeout(
                init=settings.dependency_timeout_seconds,
                query=settings.weaviate_request_timeout_seconds,
                insert=settings.weaviate_request_timeout_seconds,
            )
        ),
    )


def run(
    action: str,
    *,
    input_path: Path | None,
    chunk_lock_path: Path | None,
    confirm_collection: str | None,
) -> str:
    """Execute one bounded local collection operation and return its summary."""

    settings = Settings()
    if action == "reset":
        if confirm_collection != GUIDELINE_COLLECTION:
            raise GuidelineIndexCommandError(
                f"reset requires --confirm-collection {GUIDELINE_COLLECTION}"
            )
        records: Sequence[GuidelineVectorRecord] = ()
    else:
        if input_path is None or chunk_lock_path is None:
            raise GuidelineIndexCommandError(
                "sync and verify require --input and --chunk-lock"
            )
        records = build_records(
            input_path,
            chunk_lock_path,
            DeterministicGuidelineEmbeddingModel(),
        )

    store = WeaviateGuidelineVectorStore(_local_connection(settings))
    try:
        if action == "reset":
            store.reset()
            return f"Deleted only local collection {GUIDELINE_COLLECTION}"
        if action == "sync":
            result = store.sync(records)
            return (
                f"Indexed {result.snapshot.document_count} documents / "
                f"{result.snapshot.chunk_count} chunks: "
                f"inserted={result.inserted}, replaced={result.replaced}, "
                f"skipped={result.skipped}, deleted={result.deleted}"
            )
        snapshot = store.verify(records)
        return (
            f"Verified {snapshot.collection_name}: "
            f"{snapshot.document_count} documents / {snapshot.chunk_count} chunks"
        )
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "verify", "reset"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--chunk-lock", type=Path)
    parser.add_argument("--confirm-collection")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        print(
            run(
                args.action,
                input_path=args.input,
                chunk_lock_path=args.chunk_lock,
                confirm_collection=args.confirm_collection,
            )
        )
    except (
        GuidelineChunkBuildError,
        GuidelineEmbeddingError,
        GuidelineVectorStoreError,
        GuidelineIndexCommandError,
        WeaviateBaseError,
    ) as error:
        print(f"Guideline index error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
