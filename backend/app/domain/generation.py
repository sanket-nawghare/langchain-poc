"""Provider-neutral contracts for grounded response generation."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.domain.base import ContractModel
from app.domain.clinical import Citation, ClinicalSummaryCategory
from app.domain.guidelines import GuidelineQuery
from app.domain.workflow import ResponseDraft

MAX_GROUNDED_FACTS = 32
MAX_GROUNDED_EVIDENCE = 8

GroundedFactDisplay = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
GroundedFactDetail = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
GroundedFactStatus = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
GroundedFactTimestamp = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]


class GroundedClinicalFact(ContractModel):
    """One bounded, deidentified clinical fact selected for generation."""

    category: ClinicalSummaryCategory
    display: GroundedFactDisplay
    status: GroundedFactStatus | None = None
    effective_at: GroundedFactTimestamp | None = None
    value: GroundedFactDetail | None = None


class GroundedPatientContext(ContractModel):
    """Minimum patient context allowed to cross the model-provider boundary."""

    facts: list[GroundedClinicalFact] = Field(
        min_length=1,
        max_length=MAX_GROUNDED_FACTS,
    )


class GroundedEvidence(ContractModel):
    """One ranked application-owned citation with a required bounded excerpt."""

    rank: int = Field(ge=1, le=MAX_GROUNDED_EVIDENCE)
    citation: Citation

    @model_validator(mode="after")
    def require_excerpt(self) -> "GroundedEvidence":
        if self.citation.excerpt is None:
            raise ValueError("grounded evidence requires a citation excerpt")
        return self


class GroundedGenerationRequest(ContractModel):
    """Complete data-only payload accepted by a response generator."""

    question: GuidelineQuery
    patient_context: GroundedPatientContext
    evidence: list[GroundedEvidence] = Field(
        min_length=1,
        max_length=MAX_GROUNDED_EVIDENCE,
    )

    @model_validator(mode="after")
    def validate_ranked_evidence(self) -> "GroundedGenerationRequest":
        ranks = [item.rank for item in self.evidence]
        if ranks != list(range(1, len(self.evidence) + 1)):
            raise ValueError("grounded evidence ranks must be contiguous from one")
        chunk_ids = [item.citation.chunk_id for item in self.evidence]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("grounded evidence chunk IDs must be unique")
        return self


class ResponseGenerationMetadata(ContractModel):
    """Bounded provider-neutral telemetry safe for audit metadata."""

    generator: Literal["deterministic", "provider"]
    model_alias: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
        ]
        | None
    ) = None
    # Must cover the largest configurable llm_request_timeout_seconds (300s).
    latency_ms: int | None = Field(default=None, ge=0, le=300_000)
    input_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def provider_requires_model_alias(self) -> "ResponseGenerationMetadata":
        if self.generator == "provider" and self.model_alias is None:
            raise ValueError("provider generation metadata requires a model alias")
        if self.generator == "deterministic" and any(
            value is not None
            for value in (
                self.model_alias,
                self.latency_ms,
                self.input_tokens,
                self.output_tokens,
            )
        ):
            raise ValueError("deterministic generation cannot report provider metrics")
        return self


class ResponseGenerationResult(ContractModel):
    """Application-owned draft plus bounded audit-safe generation metadata."""

    draft: ResponseDraft
    metadata: ResponseGenerationMetadata
