"""Strict deterministic guideline PDF parser tests."""

import hashlib
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.domain import (
    GuidelineDocumentFormat,
    GuidelineLifecycleStatus,
    GuidelinePublisher,
    GuidelineSource,
    GuidelineUsePermission,
)
from app.rag import (
    GuidelineParsingBoundsError,
    GuidelineParsingEncryptedError,
    GuidelineParsingInputError,
    GuidelineParsingMalformedError,
)
from app.services.pypdf_guidelines import (
    MAX_CHUNK_CHARACTERS,
    MAX_RAW_PAGE_CHARACTERS,
    PARSER_VERSION,
    PypdfGuidelineParser,
)


def _pdf_string(value: str) -> bytes:
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("latin-1")


def write_pdf(
    path: Path,
    pages: list[str],
    *,
    encrypted: bool = False,
    javascript: bool = False,
    attachment: bool = False,
) -> None:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)  # noqa: SLF001
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        content = DecodedStreamObject()
        text_operations = b" 0 -18 Td ".join(
            b"(" + _pdf_string(line) + b") Tj" for line in text.split("\n")
        )
        content.set_data(b"BT /F1 12 Tf 72 720 Td " + text_operations + b" ET")
        page[NameObject("/Contents")] = writer._add_object(content)  # noqa: SLF001
    if javascript:
        writer.add_js("app.alert('not allowed')")
    if attachment:
        writer.add_attachment("unexpected.txt", b"not allowed")
    if encrypted:
        writer.encrypt("test-password")
    with path.open("wb") as handle:
        writer.write(handle)


def source_for(path: Path) -> GuidelineSource:
    return GuidelineSource(
        document_id="who-parser-test-v1",
        title="Synthetic parser fixture",
        publisher=GuidelinePublisher.WHO,
        canonical_url="https://www.who.int/publications/i/item/test",
        document_format=GuidelineDocumentFormat.PDF,
        publication_date=date(2026, 1, 1),
        version="test-v1",
        accessed_at=date(2026, 8, 3),
        license_name="Synthetic test permission",
        license_url="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
        use_permission=GuidelineUsePermission.LOCAL_INDEX_ONLY,
        license_reviewed_at=date(2026, 8, 3),
        license_review_note="Synthetic test document only.",
        lifecycle_status=GuidelineLifecycleStatus.CURRENT,
        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        supported_topics=["synthetic parser test"],
    )


def test_parser_is_deterministic_bounded_and_preserves_lineage(tmp_path: Path) -> None:
    path = tmp_path / "guideline.pdf"
    write_pdf(
        path,
        [
            "1 CLINICAL MANAGEMENT\n" + "bounded evidence text " * 260,
            "SECOND PAGE follow-up guidance",
        ],
    )
    parser = PypdfGuidelineParser()

    first = parser.parse(source_for(path), path, expected_page_count=2)
    second = parser.parse(source_for(path), path, expected_page_count=2)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.parser_version == PARSER_VERSION
    assert len(first.chunks) >= 3
    assert [chunk.sequence for chunk in first.chunks] == list(range(len(first.chunks)))
    assert all(0 < len(chunk.text) <= MAX_CHUNK_CHARACTERS for chunk in first.chunks)
    assert all(chunk.document_id == first.source.document_id for chunk in first.chunks)
    assert {chunk.page for chunk in first.chunks} == {1, 2}
    assert first.chunks[0].section == "1 CLINICAL MANAGEMENT"
    assert all(
        chunk.chunk_id.endswith(chunk.content_sha256[:12]) for chunk in first.chunks
    )


def test_parser_rejects_checksum_and_page_count_drift(tmp_path: Path) -> None:
    path = tmp_path / "guideline.pdf"
    write_pdf(path, ["Reviewed text"])
    reviewed_source = source_for(path)
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(GuidelineParsingInputError, match="checksum"):
        PypdfGuidelineParser().parse(
            reviewed_source,
            path,
            expected_page_count=1,
        )

    write_pdf(path, ["Reviewed text"])
    with pytest.raises(GuidelineParsingInputError, match="page count"):
        PypdfGuidelineParser().parse(source_for(path), path, expected_page_count=2)


def test_parser_rejects_encrypted_empty_and_malformed_pdfs(tmp_path: Path) -> None:
    encrypted = tmp_path / "encrypted.pdf"
    write_pdf(encrypted, ["Secret text"], encrypted=True)
    with pytest.raises(GuidelineParsingEncryptedError):
        PypdfGuidelineParser().parse(
            source_for(encrypted), encrypted, expected_page_count=1
        )

    empty = tmp_path / "empty.pdf"
    write_pdf(empty, [""])
    with pytest.raises(GuidelineParsingMalformedError, match="no extractable text"):
        PypdfGuidelineParser().parse(source_for(empty), empty, expected_page_count=1)

    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"%PDF-1.7\ninvalid\n%%EOF")
    with pytest.raises(GuidelineParsingMalformedError, match="could not be parsed"):
        PypdfGuidelineParser().parse(
            source_for(malformed), malformed, expected_page_count=1
        )


@pytest.mark.parametrize("unsafe_kind", ["javascript", "attachment"])
def test_parser_rejects_active_or_embedded_content(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    path = tmp_path / "unsafe.pdf"
    write_pdf(
        path,
        ["Reviewed text"],
        javascript=unsafe_kind == "javascript",
        attachment=unsafe_kind == "attachment",
    )

    with pytest.raises(GuidelineParsingMalformedError, match="active content"):
        PypdfGuidelineParser().parse(source_for(path), path, expected_page_count=1)


def test_parser_rejects_extracted_page_text_over_bound(tmp_path: Path) -> None:
    path = tmp_path / "oversized-text.pdf"
    write_pdf(path, ["x" * (MAX_RAW_PAGE_CHARACTERS + 1)])

    with pytest.raises(GuidelineParsingBoundsError, match="extracted text"):
        PypdfGuidelineParser().parse(source_for(path), path, expected_page_count=1)
