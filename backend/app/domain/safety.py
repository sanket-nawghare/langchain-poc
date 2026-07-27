"""Safety-result contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from app.domain.base import ContractModel, NonEmptyString


class SafetyDecision(StrEnum):
    """Permitted outcomes of safety evaluation."""

    PASS = "pass"
    REVIEW = "review"
    BLOCK = "block"


class SafetySeverity(StrEnum):
    """Severity attached to a safety reason."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


class SafetyReason(ContractModel):
    """Versionable reason emitted by a safety rule."""

    code: NonEmptyString
    message: NonEmptyString
    severity: SafetySeverity
    evidence_references: list[NonEmptyString] = Field(default_factory=list)


class SafetyResult(ContractModel):
    """Structured aggregate safety decision."""

    decision: SafetyDecision
    requires_human_review: bool
    policy_version: NonEmptyString
    reasons: list[SafetyReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def decision_matches_review_requirement(self) -> "SafetyResult":
        """Reject contradictory decision/review combinations."""

        expected_review = self.decision == SafetyDecision.REVIEW
        if self.requires_human_review != expected_review:
            raise ValueError(
                "requires_human_review must be true only for a review decision"
            )
        return self
