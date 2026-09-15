"""Strict bounded pypdf adapter for reviewed guideline documents."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from pypdf import PdfReader

from app.domain.guidelines import (
    GuidelineChunk,
    GuidelineDocumentFormat,
    GuidelineSource,
    ParsedGuidelineDocument,
)
from app.rag.parsing import (
    GuidelineParsingBoundsError,
    GuidelineParsingEncryptedError,
    GuidelineParsingInputError,
    GuidelineParsingMalformedError,
)

PARSER_VERSION: Final = "deterministic-pypdf-v1"
MAX_PDF_BYTES: Final = 4 * 1024 * 1024
MAX_PAGES: Final = 500
MAX_RAW_PAGE_CHARACTERS: Final = 50_000
MAX_DOCUMENT_CHARACTERS: Final = 1_000_000
MAX_CHUNK_CHARACTERS: Final = 2_400
MIN_SPLIT_WINDOW_CHARACTERS: Final = 1_200
CHUNK_OVERLAP_CHARACTERS: Final = 200
MAX_CHUNKS: Final = 1_000
MAX_SECTION_CHARACTERS: Final = 160

_NUMBERED_HEADING = re.compile(r"^(?:[A-Z]\.|\d+(?:\.\d+)*)\s+\S")
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?[ivxlcdm\d]+$", re.IGNORECASE)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_heading(value: str) -> bool:
    if len(value) > MAX_SECTION_CHARACTERS or _PAGE_NUMBER.fullmatch(value):
        return False
    letters = [character for character in value if character.isalpha()]
    if len(letters) < 3:
        return False
    uppercase_ratio = sum(character.isupper() for character in letters) / len(letters)
    return uppercase_ratio >= 0.8 or _NUMBERED_HEADING.match(value) is not None


def _normalize_page(raw_text: str, *, page_number: int) -> tuple[str, str]:
    if "\x00" in raw_text:
        raise GuidelineParsingMalformedError(
            f"page {page_number}: extracted text contains a null character"
        )
    normalized = unicodedata.normalize("NFKC", raw_text)
    normalized = normalized.replace("\u00ad", "").replace("\u00a0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?<=\w)-\n(?=\w)", "", normalized)

    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = " ".join(raw_line.split())
        if line:
            lines.append(line)
    section = next((line for line in lines if _is_heading(line)), f"Page {page_number}")
    return " ".join(lines), section


def _chunk_page(text: str) -> tuple[str, ...]:
    if len(text) <= MAX_CHUNK_CHARACTERS:
        return (text,)

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARACTERS, len(text))
        if end < len(text):
            split = text.rfind(
                " ",
                start + MIN_SPLIT_WINDOW_CHARACTERS,
                end + 1,
            )
            if split > start:
                end = split
        chunk = text[start:end].strip()
        if not chunk:
            raise GuidelineParsingMalformedError(
                "normalization produced an empty chunk"
            )
        chunks.append(chunk)
        if end >= len(text):
            break
        overlap_start = max(start + 1, end - CHUNK_OVERLAP_CHARACTERS)
        next_space = text.find(" ", overlap_start, end)
        start = next_space + 1 if next_space >= 0 else end
    return tuple(chunks)


def _has_unsafe_catalog_entries(reader: PdfReader) -> bool:
    root = reader.root_object
    if "/AA" in root:
        return True
    open_action_reference = root.get("/OpenAction")
    if open_action_reference is not None:
        open_action = open_action_reference.get_object()
        if not isinstance(open_action, Mapping) or open_action.get("/S") != "/GoTo":
            return True
    names_reference = root.get("/Names")
    if names_reference is None:
        return False
    names = names_reference.get_object()
    return "/JavaScript" in names or "/EmbeddedFiles" in names


class PypdfGuidelineParser:
    """Parse exact reviewed PDFs into deterministic page-confined chunks."""

    def parse(
        self,
        source: GuidelineSource,
        path: Path,
        *,
        expected_page_count: int,
    ) -> ParsedGuidelineDocument:
        if (
            not source.is_indexable
            or source.document_format is not GuidelineDocumentFormat.PDF
        ):
            raise GuidelineParsingInputError("source is not an approved indexable PDF")
        if path.is_symlink() or not path.is_file():
            raise GuidelineParsingInputError("guideline PDF is not a regular file")
        size_bytes = path.stat().st_size
        if size_bytes <= 0 or size_bytes > MAX_PDF_BYTES:
            raise GuidelineParsingBoundsError(
                "guideline PDF exceeds the file-size bound"
            )
        if _sha256_file(path) != source.content_sha256:
            raise GuidelineParsingInputError(
                "guideline PDF checksum does not match source"
            )
        if not 1 <= expected_page_count <= MAX_PAGES:
            raise GuidelineParsingBoundsError("expected page count is outside bounds")

        try:
            with path.open("rb") as handle:
                reader = PdfReader(
                    handle,
                    strict=True,
                    root_object_recovery_limit=0,
                )
                if reader.is_encrypted:
                    raise GuidelineParsingEncryptedError(
                        "encrypted guideline PDFs are not accepted"
                    )
                if len(reader.pages) != expected_page_count:
                    raise GuidelineParsingInputError(
                        "PDF page count does not match reviewed metadata"
                    )
                if _has_unsafe_catalog_entries(reader):
                    raise GuidelineParsingMalformedError(
                        "PDF contains active content or embedded files"
                    )

                chunks: list[GuidelineChunk] = []
                extracted_characters = 0
                for page_number, page in enumerate(reader.pages, start=1):
                    raw_text = page.extract_text() or ""
                    if len(raw_text) > MAX_RAW_PAGE_CHARACTERS:
                        raise GuidelineParsingBoundsError(
                            f"page {page_number}: extracted text exceeds bounds"
                        )
                    extracted_characters += len(raw_text)
                    if extracted_characters > MAX_DOCUMENT_CHARACTERS:
                        raise GuidelineParsingBoundsError(
                            "document extracted text exceeds bounds"
                        )
                    normalized, section = _normalize_page(
                        raw_text,
                        page_number=page_number,
                    )
                    if not normalized:
                        continue
                    for page_chunk_index, text in enumerate(_chunk_page(normalized)):
                        if len(chunks) >= MAX_CHUNKS:
                            raise GuidelineParsingBoundsError(
                                "document chunk count exceeds bounds"
                            )
                        content_sha256 = hashlib.sha256(
                            text.encode("utf-8")
                        ).hexdigest()
                        chunk_id = (
                            f"{source.document_id}.p{page_number:04d}."
                            f"c{page_chunk_index:03d}.{content_sha256[:12]}"
                        )
                        chunks.append(
                            GuidelineChunk(
                                chunk_id=chunk_id,
                                document_id=source.document_id,
                                text=text,
                                content_sha256=content_sha256,
                                sequence=len(chunks),
                                page=page_number,
                                section=section,
                            )
                        )
        except GuidelineParsingEncryptedError:
            raise
        except (
            GuidelineParsingBoundsError,
            GuidelineParsingInputError,
            GuidelineParsingMalformedError,
        ):
            raise
        except Exception as error:
            raise GuidelineParsingMalformedError(
                "guideline PDF could not be parsed"
            ) from error

        if not chunks:
            raise GuidelineParsingMalformedError(
                "guideline PDF contains no extractable text"
            )
        return ParsedGuidelineDocument(
            parser_version=PARSER_VERSION,
            source=source,
            chunks=chunks,
        )
