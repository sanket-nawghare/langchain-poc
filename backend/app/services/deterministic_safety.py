"""Versioned deterministic safety pre-check over normalized context."""

from app.domain.clinical import PatientSummary
from app.domain.safety import (
    SafetyDecision,
    SafetyReason,
    SafetyResult,
    SafetySeverity,
)

INITIAL_SAFETY_POLICY_VERSION = "initial-safety-v1"
URGENT_LANGUAGE = (
    "chest pain",
    "difficulty breathing",
    "severe bleeding",
    "shortness of breath",
    "suicidal",
    "overdose",
    "unconscious",
)


def _has_core_context(patient: PatientSummary) -> bool:
    return any(
        (
            patient.conditions,
            patient.allergies,
            patient.medications,
            patient.observations,
        )
    )


class DeterministicSafetyPolicy:
    """Conservative review rules without autonomous clinical decisions."""

    async def evaluate(
        self,
        *,
        query: str,
        patient: PatientSummary,
    ) -> SafetyResult:
        """Flag urgent language, missing core context, or bounded truncation."""

        normalized_query = " ".join(query.casefold().split())
        reasons: list[SafetyReason] = []
        if any(phrase in normalized_query for phrase in URGENT_LANGUAGE):
            reasons.append(
                SafetyReason(
                    code="urgent_language",
                    message="The request contains urgent language requiring review.",
                    severity=SafetySeverity.HIGH,
                    evidence_references=["request:urgent_language"],
                )
            )
        if not _has_core_context(patient):
            reasons.append(
                SafetyReason(
                    code="missing_core_context",
                    message="Core normalized patient context is unavailable.",
                    severity=SafetySeverity.WARNING,
                    evidence_references=[
                        "patient:conditions",
                        "patient:allergies",
                        "patient:medications",
                        "patient:observations",
                    ],
                )
            )
        if patient.truncated_categories:
            reasons.append(
                SafetyReason(
                    code="patient_context_truncated",
                    message="One or more patient context collections are truncated.",
                    severity=SafetySeverity.WARNING,
                    evidence_references=[
                        f"patient:{category}"
                        for category in patient.truncated_categories
                    ],
                )
            )

        requires_review = bool(reasons)
        return SafetyResult(
            decision=(
                SafetyDecision.REVIEW if requires_review else SafetyDecision.PASS
            ),
            requires_human_review=requires_review,
            policy_version=INITIAL_SAFETY_POLICY_VERSION,
            reasons=reasons,
        )
