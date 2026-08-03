"""Provider-neutral guideline provenance and retrieval contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, StringConstraints, model_validator

from app.domain.base import ContractModel
from app.domain.clinical import Citation

GuidelineIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
GuidelineTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
GuidelineQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
GuidelineChunkText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=3000),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$"),
]
ShortMetadata = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ReviewNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
Topic = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]


class GuidelinePublisher(StrEnum):
    """Publishers eligible for per-document review."""

    WHO = "who"
    CDC = "cdc"
    NICE = "nice"
    ADA = "ada"


class GuidelineDocumentFormat(StrEnum):
    """Document formats accepted by the initial parser boundary."""

    HTML = "html"
    PDF = "pdf"


class GuidelineUsePermission(StrEnum):
    """Reviewed content-use decision for one exact document."""

    REDISTRIBUTE_AND_INDEX = "redistribute_and_index"
    LOCAL_INDEX_ONLY = "local_index_only"
    LINK_ONLY = "link_only"
    PROHIBITED = "prohibited"


class GuidelineLifecycleStatus(StrEnum):
    """Publisher lifecycle state recorded during source review."""

    CURRENT = "current"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class EvidenceAssessment(StrEnum):
    """Application decision over normalized retrieval evidence."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


class GuidelineSource(ContractModel):
    """Reviewed provenance and permission metadata for one document version."""

    document_id: GuidelineIdentifier
    title: GuidelineTitle
    publisher: GuidelinePublisher
    canonical_url: AnyHttpUrl
    document_format: GuidelineDocumentFormat
    publication_date: date
    version: ShortMetadata
    accessed_at: date
    license_name: ShortMetadata
    license_url: AnyHttpUrl | None = None
    use_permission: GuidelineUsePermission
    license_reviewed_at: date
    license_review_note: ReviewNote
    lifecycle_status: GuidelineLifecycleStatus
    content_sha256: Sha256Digest
    supported_topics: list[Topic] = Field(min_length=1, max_length=16)
    language: Literal["en"] = "en"

    @model_validator(mode="after")
    def validate_review_record(self) -> "GuidelineSource":
        if self.publication_date > self.accessed_at:
            raise ValueError("publication_date must not follow accessed_at")
        if self.license_reviewed_at > self.accessed_at:
            raise ValueError("license_reviewed_at must not follow accessed_at")
        if len(set(self.supported_topics)) != len(self.supported_topics):
            raise ValueError("supported_topics must be unique")
        return self

    @property
    def is_indexable(self) -> bool:
        """Return whether the reviewed document may enter the local index."""

        return self.lifecycle_status is GuidelineLifecycleStatus.CURRENT and (
            self.use_permission
            in {
                GuidelineUsePermission.REDISTRIBUTE_AND_INDEX,
                GuidelineUsePermission.LOCAL_INDEX_ONLY,
            }
        )


class GuidelineChunk(ContractModel):
    """Bounded extracted content with stable document lineage."""

    chunk_id: GuidelineIdentifier
    document_id: GuidelineIdentifier
    text: GuidelineChunkText
    content_sha256: Sha256Digest
    sequence: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    section: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        ]
        | None
    ) = None


class GuidelineRetrievalRequest(ContractModel):
    """Deidentified and bounded query passed to a retrieval capability."""

    clinical_query: GuidelineQuery
    top_k: int = Field(default=5, ge=1, le=8)
    publishers: list[GuidelinePublisher] = Field(default_factory=list, max_length=4)
    as_of: date

    @model_validator(mode="after")
    def validate_publishers(self) -> "GuidelineRetrievalRequest":
        if len(set(self.publishers)) != len(self.publishers):
            raise ValueError("publishers must be unique")
        return self


class GuidelineRetrievalMatch(ContractModel):
    """One ranked, normalized match with trusted citation metadata."""

    source: GuidelineSource
    chunk: GuidelineChunk
    citation: Citation
    relevance_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1, le=8)

    @model_validator(mode="after")
    def validate_lineage(self) -> "GuidelineRetrievalMatch":
        if not self.source.is_indexable:
            raise ValueError("retrieval source must be current and indexable")
        if self.chunk.document_id != self.source.document_id:
            raise ValueError("chunk document_id must match source document_id")
        if self.citation.document_id != self.source.document_id:
            raise ValueError("citation document_id must match source document_id")
        if self.citation.chunk_id != self.chunk.chunk_id:
            raise ValueError("citation chunk_id must match chunk chunk_id")
        if self.citation.title != self.source.title:
            raise ValueError("citation title must match source title")
        if self.citation.publisher != self.source.publisher.value:
            raise ValueError("citation publisher must match source publisher")
        if str(self.citation.source_url) != str(self.source.canonical_url):
            raise ValueError("citation source_url must match source canonical_url")
        if self.citation.page != self.chunk.page:
            raise ValueError("citation page must match chunk page")
        return self


class GuidelineRetrievalResult(ContractModel):
    """Deterministic application-owned evidence assessment."""

    assessment: EvidenceAssessment
    policy_version: ShortMetadata
    query_fingerprint: Sha256Digest
    matches: list[GuidelineRetrievalMatch] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_evidence(self) -> "GuidelineRetrievalResult":
        if self.assessment is EvidenceAssessment.SUFFICIENT and not self.matches:
            raise ValueError("sufficient evidence requires at least one match")
        if self.assessment is EvidenceAssessment.CONFLICTING and len(self.matches) < 2:
            raise ValueError("conflicting evidence requires at least two matches")

        ranks = [match.rank for match in self.matches]
        if ranks != list(range(1, len(self.matches) + 1)):
            raise ValueError("match ranks must be ordered and contiguous from one")
        chunk_ids = [match.chunk.chunk_id for match in self.matches]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("retrieval matches must have unique chunk IDs")
        return self
