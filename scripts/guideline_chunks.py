"""Build and verify deterministic ignored guideline chunk output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from app.domain.guidelines import ParsedGuidelineDocument
from app.services.pypdf_guidelines import PARSER_VERSION, PypdfGuidelineParser
from scripts.guideline_corpus import GuidelineCorpusError, verify_local

CHUNK_LOCK_CONTENT = "guideline-chunk-checksums-only"
CHUNK_OUTPUT_CONTENT = "ignored-local-guideline-chunks"
MAX_DOCUMENTS = 8

JsonObject = dict[str, Any]


class GuidelineChunkBuildError(RuntimeError):
    """Safe deterministic chunk build or verification failure."""


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuidelineChunkBuildError(f"{path.name}: invalid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise GuidelineChunkBuildError(f"{path.name}: expected a JSON object")
    return cast(JsonObject, value)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise GuidelineChunkBuildError(f"{label}: expected an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise GuidelineChunkBuildError(f"{label}: expected an array")
    return cast(Sequence[object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        difference = sorted(set(value).symmetric_difference(expected))
        raise GuidelineChunkBuildError(
            f"{label}: unexpected or missing fields: {difference}"
        )


def build_documents(
    corpus_lock_path: Path,
    document_dir: Path,
) -> tuple[ParsedGuidelineDocument, ...]:
    """Verify then parse every reviewed document in lock order."""

    try:
        locked_documents = verify_local(corpus_lock_path, document_dir)
    except GuidelineCorpusError as error:
        raise GuidelineChunkBuildError(
            "reviewed guideline corpus is invalid"
        ) from error
    parser = PypdfGuidelineParser()
    return tuple(
        parser.parse(
            document.source,
            document_dir / document.filename,
            expected_page_count=document.page_count,
        )
        for document in locked_documents
    )


def chunk_summary(
    documents: Sequence[ParsedGuidelineDocument],
) -> JsonObject:
    """Create a content-free deterministic summary suitable for Git."""

    return {
        "schema_version": 1,
        "content": CHUNK_LOCK_CONTENT,
        "parser_version": PARSER_VERSION,
        "documents": [
            {
                "document_id": document.source.document_id,
                "source_sha256": document.source.content_sha256,
                "chunk_count": len(document.chunks),
                "chunks_sha256": _canonical_sha256(
                    [chunk.model_dump(mode="json") for chunk in document.chunks]
                ),
                "first_chunk_id": document.chunks[0].chunk_id,
                "last_chunk_id": document.chunks[-1].chunk_id,
            }
            for document in documents
        ],
    }


def verify_chunk_lock(summary: JsonObject, chunk_lock_path: Path) -> None:
    """Require exact agreement with the committed content-free chunk lock."""

    lock = _read_json(chunk_lock_path)
    root_keys = {"schema_version", "content", "parser_version", "documents"}
    _exact_keys(lock, root_keys, label="chunk lock")
    if lock != summary:
        raise GuidelineChunkBuildError("generated chunks do not match chunk lock")


def write_processed_output(
    documents: Sequence[ParsedGuidelineDocument],
    output_path: Path,
) -> None:
    """Atomically write ignored strict chunk output for later local ingestion."""

    output = {
        "schema_version": 1,
        "content": CHUNK_OUTPUT_CONTENT,
        "parser_version": PARSER_VERSION,
        "documents": [document.model_dump(mode="json") for document in documents],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(output, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_name, output_path)
        temporary_name = None
    except OSError as error:
        raise GuidelineChunkBuildError("could not write local chunk output") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def load_processed_output(output_path: Path) -> tuple[ParsedGuidelineDocument, ...]:
    """Strictly reload ignored output without accepting provider fields."""

    output = _read_json(output_path)
    root_keys = {"schema_version", "content", "parser_version", "documents"}
    _exact_keys(output, root_keys, label="chunk output")
    if (
        output["schema_version"] != 1
        or output["content"] != CHUNK_OUTPUT_CONTENT
        or output["parser_version"] != PARSER_VERSION
    ):
        raise GuidelineChunkBuildError("unsupported local chunk output")
    values = _sequence(output["documents"], label="chunk output documents")
    if not values or len(values) > MAX_DOCUMENTS:
        raise GuidelineChunkBuildError("chunk output document count is outside bounds")
    try:
        documents = tuple(
            ParsedGuidelineDocument.model_validate(value) for value in values
        )
    except ValidationError as error:
        raise GuidelineChunkBuildError("local chunk output is invalid") from error
    if any(document.parser_version != PARSER_VERSION for document in documents):
        raise GuidelineChunkBuildError("document parser version does not match output")
    return documents


def build_and_verify(
    corpus_lock_path: Path,
    document_dir: Path,
    chunk_lock_path: Path,
    output_path: Path,
) -> tuple[ParsedGuidelineDocument, ...]:
    """Parse, verify deterministic summary, write, and strictly reload output."""

    documents = build_documents(corpus_lock_path, document_dir)
    verify_chunk_lock(chunk_summary(documents), chunk_lock_path)
    write_processed_output(documents, output_path)
    reloaded = load_processed_output(output_path)
    if reloaded != documents:
        raise GuidelineChunkBuildError(
            "local chunk output changed during serialization"
        )
    return documents


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-lock", type=Path, required=True)
    parser.add_argument("--document-dir", type=Path, required=True)
    parser.add_argument("--chunk-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        documents = build_and_verify(
            args.corpus_lock,
            args.document_dir,
            args.chunk_lock,
            args.output,
        )
    except GuidelineChunkBuildError as error:
        print(f"Guideline chunk error: {error}")
        return 1
    chunk_count = sum(len(document.chunks) for document in documents)
    print(
        f"Built and verified local guideline chunks: "
        f"{len(documents)} documents, {chunk_count} chunks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
