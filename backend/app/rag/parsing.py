"""Application-owned guideline parsing capability and safe failures."""

from pathlib import Path
from typing import Protocol

from app.domain.guidelines import GuidelineSource, ParsedGuidelineDocument


class GuidelineParsingError(RuntimeError):
    """Base parsing failure safe to report outside the parser adapter."""


class GuidelineParsingInputError(GuidelineParsingError):
    """The local source or its reviewed lineage is invalid."""


class GuidelineParsingEncryptedError(GuidelineParsingError):
    """The reviewed source unexpectedly requires PDF decryption."""


class GuidelineParsingMalformedError(GuidelineParsingError):
    """The PDF is malformed, structurally unsafe, or cannot yield text."""


class GuidelineParsingBoundsError(GuidelineParsingError):
    """Parsing exceeded an application-owned resource or output bound."""


class GuidelineDocumentParser(Protocol):
    """Provider-neutral local parser for one reviewed document."""

    def parse(
        self,
        source: GuidelineSource,
        path: Path,
        *,
        expected_page_count: int,
    ) -> ParsedGuidelineDocument:
        """Return deterministic chunks or raise a typed safe failure."""
