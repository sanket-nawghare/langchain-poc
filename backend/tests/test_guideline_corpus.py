"""Reviewed guideline corpus lock and local-file verification tests."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.guideline_corpus import (
    MAX_DOCUMENT_BYTES,
    GuidelineCorpusError,
    load_corpus_lock,
    verify_local,
)

PDF_BYTES = b"%PDF-1.7\nsynthetic guideline test only\n%%EOF\n"


def source(document_id: str, checksum: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "title": "Synthetic guideline contract fixture",
        "publisher": "who",
        "canonical_url": "https://www.who.int/publications/i/item/test",
        "document_format": "pdf",
        "publication_date": "2026-01-01",
        "version": "test-v1",
        "accessed_at": "2026-08-03",
        "license_name": "CC BY-NC-SA 3.0 IGO",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
        "use_permission": "local_index_only",
        "license_reviewed_at": "2026-08-03",
        "license_review_note": "Synthetic contract fixture only.",
        "lifecycle_status": "current",
        "content_sha256": checksum,
        "supported_topics": ["synthetic topic"],
        "language": "en",
    }


def document(
    document_id: str,
    filename: str,
    scenario: str,
    checksum: str,
    size_bytes: int = len(PDF_BYTES),
) -> dict[str, Any]:
    return {
        "source": source(document_id, checksum),
        "artifact": {
            "download_url": (
                "https://iris.who.int/server/api/core/bitstreams/test/content"
            ),
            "filename": filename,
            "page_count": 1,
            "size_bytes": size_bytes,
        },
        "supported_scenarios": [scenario],
    }


def write_lock(
    path: Path,
    *,
    permission: str = "local_index_only",
    extra_document_field: bool = False,
) -> None:
    checksum = hashlib.sha256(PDF_BYTES).hexdigest()
    documents = [
        document(
            "who-diabetes-test",
            "diabetes.pdf",
            "metabolic-01",
            checksum,
        ),
        document(
            "who-hypertension-test",
            "hypertension.pdf",
            "cardiovascular-01",
            checksum,
        ),
    ]
    documents[0]["source"]["use_permission"] = permission
    if extra_document_field:
        documents[0]["_additional"] = {"provider": "must not cross boundary"}
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


def write_documents(document_dir: Path) -> None:
    document_dir.mkdir()
    (document_dir / "diabetes.pdf").write_bytes(PDF_BYTES)
    (document_dir / "hypertension.pdf").write_bytes(PDF_BYTES)


def test_verifies_exact_reviewed_local_corpus(tmp_path: Path) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    document_dir = tmp_path / "documents"
    write_lock(lock_path)
    write_documents(document_dir)

    verified = verify_local(lock_path, document_dir)

    assert [item.source.document_id for item in verified] == [
        "who-diabetes-test",
        "who-hypertension-test",
    ]


def test_rejects_missing_or_unexpected_documents(tmp_path: Path) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    document_dir = tmp_path / "documents"
    write_lock(lock_path)
    write_documents(document_dir)
    (document_dir / "hypertension.pdf").unlink()

    with pytest.raises(GuidelineCorpusError, match="missing or unexpected"):
        verify_local(lock_path, document_dir)

    (document_dir / "hypertension.pdf").write_bytes(PDF_BYTES)
    (document_dir / "unreviewed.pdf").write_bytes(PDF_BYTES)
    with pytest.raises(GuidelineCorpusError, match="missing or unexpected"):
        verify_local(lock_path, document_dir)


def test_rejects_checksum_or_pdf_envelope_drift(tmp_path: Path) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    document_dir = tmp_path / "documents"
    write_lock(lock_path)
    write_documents(document_dir)
    (document_dir / "diabetes.pdf").write_bytes(PDF_BYTES.replace(b"test", b"best"))

    with pytest.raises(GuidelineCorpusError, match="sha256"):
        verify_local(lock_path, document_dir)

    (document_dir / "diabetes.pdf").write_bytes(b"not a pdf".ljust(len(PDF_BYTES)))
    with pytest.raises(GuidelineCorpusError, match="invalid PDF"):
        verify_local(lock_path, document_dir)


def test_rejects_oversized_input_before_hashing(tmp_path: Path) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    document_dir = tmp_path / "documents"
    write_lock(lock_path)
    write_documents(document_dir)
    with (document_dir / "diabetes.pdf").open("wb") as handle:
        handle.truncate(MAX_DOCUMENT_BYTES + 1)

    with pytest.raises(GuidelineCorpusError, match="exceeds size limit"):
        verify_local(lock_path, document_dir)


@pytest.mark.parametrize("permission", ["link_only", "prohibited"])
def test_rejects_documents_without_index_permission(
    tmp_path: Path,
    permission: str,
) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    write_lock(lock_path, permission=permission)

    with pytest.raises(GuidelineCorpusError, match="not approved for indexing"):
        load_corpus_lock(lock_path)


def test_rejects_provider_fields_and_unapproved_source_hosts(tmp_path: Path) -> None:
    lock_path = tmp_path / "corpus-lock.json"
    write_lock(lock_path, extra_document_field=True)
    with pytest.raises(GuidelineCorpusError, match="unexpected or missing fields"):
        load_corpus_lock(lock_path)

    write_lock(lock_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["documents"][0]["artifact"]["download_url"] = (
        "https://provider.example.test/document.pdf"
    )
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(GuidelineCorpusError, match="outside the approved source"):
        load_corpus_lock(lock_path)

    write_lock(lock_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["documents"][0]["source"]["canonical_url"] = (
        "https://provider.example.test/document"
    )
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(GuidelineCorpusError, match="does not match publisher"):
        load_corpus_lock(lock_path)
