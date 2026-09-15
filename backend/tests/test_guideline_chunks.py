"""Deterministic local guideline chunk-output tests."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest
from scripts.guideline_chunks import (
    GuidelineChunkBuildError,
    chunk_summary,
    load_processed_output,
    verify_chunk_lock,
    write_processed_output,
)

from app.domain import (
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineSource,
    GuidelineUsePermission,
    ParsedGuidelineDocument,
)
from app.services.pypdf_guidelines import PARSER_VERSION


def parsed_document() -> ParsedGuidelineDocument:
    source = GuidelineSource(
        document_id="who-chunk-output-test",
        title="Synthetic chunk output fixture",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://www.who.int/publications/i/item/test",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2026, 1, 1),
        version="test-v1",
        accessed_at=date(2026, 8, 3),
        license_name="Synthetic permission",
        license_url="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 8, 3),
        license_review_note="Synthetic test record only.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256=sha256(b"synthetic source").hexdigest(),
        supported_topics=["synthetic output"],
    )
    text = "Synthetic guideline content without patient context."
    return ParsedGuidelineDocument(
        parser_version=PARSER_VERSION,
        source=source,
        chunks=[
            GuidelineChunk(
                chunk_id="who-chunk-output-test.p0001.c000.0123456789ab",
                document_id=source.document_id,
                text=text,
                content_sha256=sha256(text.encode()).hexdigest(),
                sequence=0,
                page=1,
                section="SYNTHETIC SECTION",
            )
        ],
    )


def test_chunk_summary_is_deterministic_and_contains_no_text() -> None:
    document = parsed_document()

    first = chunk_summary([document])
    second = chunk_summary([document])

    assert first == second
    serialized = json.dumps(first)
    assert document.chunks[0].text not in serialized
    assert first["documents"][0]["chunk_count"] == 1


def test_processed_output_round_trips_without_patient_contract_fields(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "chunks.json"
    document = parsed_document()

    write_processed_output([document], output_path)
    reloaded = load_processed_output(output_path)

    assert reloaded == (document,)
    serialized = output_path.read_text(encoding="utf-8")
    assert '"patient_id"' not in serialized
    assert '"patient_summary"' not in serialized


def test_rejects_chunk_lock_drift_and_provider_output_fields(tmp_path: Path) -> None:
    document = parsed_document()
    summary = chunk_summary([document])
    lock_path = tmp_path / "chunk-lock.json"
    lock_path.write_text(json.dumps(summary), encoding="utf-8")
    verify_chunk_lock(summary, lock_path)

    changed = json.loads(lock_path.read_text(encoding="utf-8"))
    changed["documents"][0]["chunk_count"] = 2
    lock_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(GuidelineChunkBuildError, match="do not match"):
        verify_chunk_lock(summary, lock_path)

    output_path = tmp_path / "chunks.json"
    write_processed_output([document], output_path)
    output = json.loads(output_path.read_text(encoding="utf-8"))
    output["documents"][0]["_additional"] = {"provider": "must be rejected"}
    output_path.write_text(json.dumps(output), encoding="utf-8")
    with pytest.raises(GuidelineChunkBuildError, match="invalid"):
        load_processed_output(output_path)
