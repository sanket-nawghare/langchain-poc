"""Acquire and verify the reviewed, checksum-locked guideline corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.domain.guidelines import (
    GuidelineDocumentFormat,
    GuidelinePublisher,
    GuidelineSource,
    GuidelineUsePermission,
)

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_PAGES = 500
MAX_DOCUMENTS = 8
DOWNLOAD_TIMEOUT_SECONDS = 120
LOCK_CONTENT = "reviewed-guideline-provenance-and-checksums-only"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"iris.who.int"})
ALLOWED_CANONICAL_HOSTS = {
    GuidelinePublisher.WHO: frozenset({"who.int", "www.who.int"}),
}
SUPPORTED_SCENARIOS = frozenset({"metabolic-01", "cardiovascular-01"})

JsonObject = dict[str, Any]


class GuidelineCorpusError(RuntimeError):
    """Safe local corpus acquisition or verification failure."""


@dataclass(frozen=True)
class LockedGuidelineDocument:
    """Validated source and local-artifact requirements from the corpus lock."""

    source: GuidelineSource
    filename: str
    download_url: str
    size_bytes: int
    page_count: int
    supported_scenarios: tuple[str, ...]


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuidelineCorpusError(f"{path.name}: invalid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise GuidelineCorpusError(f"{path.name}: expected a JSON object")
    return cast(JsonObject, value)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise GuidelineCorpusError(f"{label}: expected an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise GuidelineCorpusError(f"{label}: expected an array")
    return cast(Sequence[object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        difference = sorted(actual.symmetric_difference(expected))
        raise GuidelineCorpusError(
            f"{label}: unexpected or missing fields: {difference}"
        )


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuidelineCorpusError(f"{label}: expected a non-empty string")
    return value.strip()


def _required_int(value: object, *, label: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise GuidelineCorpusError(f"{label}: expected an integer >= {minimum}")
    return value


def _validate_download_url(value: object, *, label: str) -> str:
    url = _required_string(value, label=label)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise GuidelineCorpusError(f"{label}: URL is outside the approved source")
    return url


def _validate_filename(value: object, *, label: str) -> str:
    filename = _required_string(value, label=label)
    if Path(filename).name != filename or not filename.endswith(".pdf"):
        raise GuidelineCorpusError(f"{label}: expected a safe PDF filename")
    return filename


def _parse_document(value: object, *, index: int) -> LockedGuidelineDocument:
    label = f"documents[{index}]"
    raw = _mapping(value, label=label)
    _exact_keys(raw, {"source", "artifact", "supported_scenarios"}, label=label)

    try:
        source = GuidelineSource.model_validate(raw["source"])
    except ValidationError as error:
        raise GuidelineCorpusError(f"{label}.source: invalid source review") from error
    if not source.is_indexable:
        raise GuidelineCorpusError(
            f"{label}.source: document is not approved for indexing"
        )
    if source.use_permission is not GuidelineUsePermission.LOCAL_INDEX_ONLY:
        raise GuidelineCorpusError(
            f"{label}.source: starter corpus must remain local-index-only"
        )
    if source.document_format is not GuidelineDocumentFormat.PDF:
        raise GuidelineCorpusError(f"{label}.source: starter corpus requires PDF")
    if source.license_url is None:
        raise GuidelineCorpusError(
            f"{label}.source: approved content requires license_url"
        )
    canonical_host = urlsplit(str(source.canonical_url)).hostname
    if canonical_host not in ALLOWED_CANONICAL_HOSTS.get(source.publisher, frozenset()):
        raise GuidelineCorpusError(
            f"{label}.source: canonical URL does not match publisher"
        )

    artifact = _mapping(raw["artifact"], label=f"{label}.artifact")
    _exact_keys(
        artifact,
        {"download_url", "filename", "page_count", "size_bytes"},
        label=f"{label}.artifact",
    )
    filename = _validate_filename(
        artifact["filename"],
        label=f"{label}.artifact.filename",
    )
    download_url = _validate_download_url(
        artifact["download_url"],
        label=f"{label}.artifact.download_url",
    )
    size_bytes = _required_int(
        artifact["size_bytes"],
        label=f"{label}.artifact.size_bytes",
    )
    if size_bytes > MAX_DOCUMENT_BYTES:
        raise GuidelineCorpusError(f"{label}.artifact: document exceeds size limit")
    page_count = _required_int(
        artifact["page_count"],
        label=f"{label}.artifact.page_count",
    )
    if page_count > MAX_DOCUMENT_PAGES:
        raise GuidelineCorpusError(f"{label}.artifact: page count exceeds limit")

    scenarios = tuple(
        _required_string(item, label=f"{label}.supported_scenarios")
        for item in _sequence(
            raw["supported_scenarios"],
            label=f"{label}.supported_scenarios",
        )
    )
    if not scenarios or len(set(scenarios)) != len(scenarios):
        raise GuidelineCorpusError(f"{label}: scenarios must be non-empty and unique")
    if not set(scenarios).issubset(SUPPORTED_SCENARIOS):
        raise GuidelineCorpusError(f"{label}: unsupported scenario")

    return LockedGuidelineDocument(
        source=source,
        filename=filename,
        download_url=download_url,
        size_bytes=size_bytes,
        page_count=page_count,
        supported_scenarios=scenarios,
    )


def load_corpus_lock(lock_path: Path) -> tuple[LockedGuidelineDocument, ...]:
    """Load and strictly validate metadata-only corpus provenance."""

    lock = _read_json(lock_path)
    _exact_keys(lock, {"schema_version", "content", "documents"}, label="lock")
    if lock["schema_version"] != 1 or lock["content"] != LOCK_CONTENT:
        raise GuidelineCorpusError("unsupported guideline corpus lock")

    raw_documents = _sequence(lock["documents"], label="documents")
    if not raw_documents or len(raw_documents) > MAX_DOCUMENTS:
        raise GuidelineCorpusError("documents: expected between 1 and 8 entries")
    documents = tuple(
        _parse_document(value, index=index) for index, value in enumerate(raw_documents)
    )
    document_ids = [document.source.document_id for document in documents]
    filenames = [document.filename for document in documents]
    if len(set(document_ids)) != len(document_ids):
        raise GuidelineCorpusError("documents: duplicate document_id")
    if len(set(filenames)) != len(filenames):
        raise GuidelineCorpusError("documents: duplicate filename")
    if {
        scenario for document in documents for scenario in document.supported_scenarios
    } != (SUPPORTED_SCENARIOS):
        raise GuidelineCorpusError("documents: starter scenarios are incomplete")
    return documents


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_document(document: LockedGuidelineDocument, path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise GuidelineCorpusError(f"{document.filename}: missing regular file")
    actual_size = path.stat().st_size
    if actual_size > MAX_DOCUMENT_BYTES:
        raise GuidelineCorpusError(f"{document.filename}: document exceeds size limit")
    if actual_size != document.size_bytes:
        raise GuidelineCorpusError(f"{document.filename}: size does not match lock")
    with path.open("rb") as handle:
        header = handle.read(5)
        handle.seek(max(0, actual_size - 1024))
        trailer = handle.read()
    if header != b"%PDF-" or b"%%EOF" not in trailer:
        raise GuidelineCorpusError(f"{document.filename}: invalid PDF envelope")
    if _sha256(path) != document.source.content_sha256:
        raise GuidelineCorpusError(f"{document.filename}: sha256 does not match lock")


def verify_local(
    lock_path: Path, document_dir: Path
) -> tuple[LockedGuidelineDocument, ...]:
    """Verify exact local files against reviewed metadata and checksums."""

    documents = load_corpus_lock(lock_path)
    if not document_dir.is_dir():
        raise GuidelineCorpusError("guideline document directory is missing")
    expected = {document.filename for document in documents}
    actual = {path.name for path in document_dir.iterdir()}
    if actual != expected:
        raise GuidelineCorpusError(
            "guideline document directory has missing or unexpected files"
        )
    for document in documents:
        _verify_document(document, document_dir / document.filename)
    return documents


def _download(document: LockedGuidelineDocument, document_dir: Path) -> None:
    destination = document_dir / document.filename
    if destination.exists():
        _verify_document(document, destination)
        return

    request = urllib.request.Request(
        document.download_url,
        headers={"User-Agent": "clinical-workflow-guideline-fetch/1.0"},
    )
    temporary_name: str | None = None
    try:
        with (
            urllib.request.urlopen(
                request, timeout=DOWNLOAD_TIMEOUT_SECONDS
            ) as response,
            tempfile.NamedTemporaryFile(
                dir=document_dir,
                prefix=f".{document.filename}.",
                suffix=".part",
                delete=False,
            ) as temporary,
        ):
            temporary_name = temporary.name
            total = 0
            while block := response.read(64 * 1024):
                total += len(block)
                if total > MAX_DOCUMENT_BYTES:
                    raise GuidelineCorpusError(
                        f"{document.filename}: download exceeds size limit"
                    )
                temporary.write(block)
        temporary_path = Path(temporary_name)
        _verify_document(document, temporary_path)
        os.replace(temporary_path, destination)
        temporary_name = None
    except (OSError, urllib.error.URLError) as error:
        raise GuidelineCorpusError(
            f"{document.filename}: guideline download failed"
        ) from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def fetch_local(lock_path: Path, document_dir: Path) -> None:
    """Download missing reviewed documents and verify the complete corpus."""

    documents = load_corpus_lock(lock_path)
    document_dir.mkdir(parents=True, exist_ok=True)
    unexpected = {path.name for path in document_dir.iterdir()} - {
        document.filename for document in documents
    }
    if unexpected:
        raise GuidelineCorpusError("guideline document directory has unexpected files")
    for document in documents:
        _download(document, document_dir)
    verify_local(lock_path, document_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("fetch", "verify"):
        action = subparsers.add_parser(command)
        action.add_argument("--lock", type=Path, required=True)
        action.add_argument("--document-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "fetch":
            fetch_local(args.lock, args.document_dir)
            print("Fetched and verified reviewed local guideline corpus")
        else:
            documents = verify_local(args.lock, args.document_dir)
            print(
                f"Verified reviewed local guideline corpus: {len(documents)} documents"
            )
    except GuidelineCorpusError as error:
        print(f"Guideline corpus error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
