"""Versioned deterministic safety pre-check over normalized context."""

import re
from dataclasses import dataclass

from app.domain.clinical import Citation, PatientSummary
from app.domain.safety import (
    SafetyDecision,
    SafetyReason,
    SafetyResult,
    SafetySeverity,
)
from app.domain.workflow import ResponseDraft

SAFETY_PRECHECK_POLICY_VERSION = "safety-precheck-v1"
SAFETY_POST_GENERATION_POLICY_VERSION = "safety-post-generation-v1"
INITIAL_SAFETY_POLICY_VERSION = SAFETY_PRECHECK_POLICY_VERSION
URGENT_LANGUAGE = (
    "chest pain",
    "difficulty breathing",
    "severe bleeding",
    "shortness of breath",
    "suicidal",
    "overdose",
    "unconscious",
)
SAFETY_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
AUTONOMOUS_MEDICATION_PATTERN = re.compile(
    r"(\b(start|stop|increase|decrease|double|halve|change|changed|adjust)\b"
    r".{0,80}\b(medication|medications|medicine|medicines|dose|dosage|tablet|capsule|mg|insulin)\b)"
    r"|(\b(medication|medications|medicine|medicines|dose|dosage|tablet|capsule|mg|insulin)\b"
    r".{0,80}\b(start|stop|increase|decrease|double|halve|change|changed|adjust)\b)",
    re.IGNORECASE | re.DOTALL,
)
DIAGNOSIS_OR_PRESCRIBING_PATTERN = re.compile(
    r"\b(i diagnose|diagnosis is|you have|i prescribe|prescribe you|"
    r"prescription for)\b",
    re.IGNORECASE,
)
GENERIC_MEDICATION_ALLERGY_TERMS = frozenset(
    {
        "allergy",
        "allergies",
        "allergic",
        "capsule",
        "daily",
        "dose",
        "drug",
        "medication",
        "medicine",
        "oral",
        "tablet",
    }
)


@dataclass(frozen=True)
class SafetyRule:
    """Stable rule metadata for policy-versioned deterministic routing."""

    code: str
    message: str
    severity: SafetySeverity
    evidence_references: tuple[str, ...]

    def reason(
        self,
        *,
        evidence_references: tuple[str, ...] | None = None,
    ) -> SafetyReason:
        return SafetyReason(
            code=self.code,
            message=self.message,
            severity=self.severity,
            evidence_references=list(evidence_references or self.evidence_references),
        )


SAFETY_RULES: dict[str, SafetyRule] = {
    "urgent_language": SafetyRule(
        code="urgent_language",
        message="The request contains urgent language requiring review.",
        severity=SafetySeverity.HIGH,
        evidence_references=("request:urgent_language",),
    ),
    "medication_allergy_conflict": SafetyRule(
        code="medication_allergy_conflict",
        message="Medication and allergy context may conflict and requires review.",
        severity=SafetySeverity.HIGH,
        evidence_references=("patient:allergies", "patient:medications"),
    ),
    "request_autonomous_medication_change": SafetyRule(
        code="request_autonomous_medication_change",
        message="The request asks about changing medication and requires review.",
        severity=SafetySeverity.HIGH,
        evidence_references=("request:medication_change",),
    ),
    "missing_core_context": SafetyRule(
        code="missing_core_context",
        message="Core normalized patient context is unavailable.",
        severity=SafetySeverity.WARNING,
        evidence_references=(
            "patient:conditions",
            "patient:allergies",
            "patient:medications",
            "patient:observations",
        ),
    ),
    "patient_context_truncated": SafetyRule(
        code="patient_context_truncated",
        message="One or more patient context collections are truncated.",
        severity=SafetySeverity.WARNING,
        evidence_references=(),
    ),
    "draft_autonomous_medication_change": SafetyRule(
        code="draft_autonomous_medication_change",
        message="Generated draft includes medication-change language requiring review.",
        severity=SafetySeverity.HIGH,
        evidence_references=("draft:answer",),
    ),
    "draft_diagnosis_or_prescribing": SafetyRule(
        code="draft_diagnosis_or_prescribing",
        message="Generated draft appears to diagnose or prescribe and is blocked.",
        severity=SafetySeverity.HIGH,
        evidence_references=("draft:answer",),
    ),
    "draft_missing_grounding_signal": SafetyRule(
        code="draft_missing_grounding_signal",
        message="Generated draft does not include an evidence-grounding signal.",
        severity=SafetySeverity.WARNING,
        evidence_references=("draft:answer", "guidelines:citations"),
    ),
}


def _has_core_context(patient: PatientSummary) -> bool:
    return any(
        (
            patient.conditions,
            patient.allergies,
            patient.medications,
            patient.observations,
        )
    )


def _clinical_terms(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {
        token
        for token in SAFETY_TOKEN_PATTERN.findall(value.casefold())
        if len(token) >= 3 and token not in GENERIC_MEDICATION_ALLERGY_TERMS
    }


def _record_terms(*values: str | None) -> set[str]:
    terms: set[str] = set()
    for value in values:
        terms.update(_clinical_terms(value))
    return terms


def _has_medication_allergy_conflict(patient: PatientSummary) -> bool:
    allergy_terms: set[str] = set()
    for allergy in patient.allergies:
        allergy_terms.update(
            _record_terms(allergy.code, allergy.display, allergy.value)
        )
    if not allergy_terms:
        return False
    for medication in patient.medications:
        medication_terms = _record_terms(
            medication.code,
            medication.display,
            medication.value,
        )
        if allergy_terms & medication_terms:
            return True
    return False


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
            reasons.append(SAFETY_RULES["urgent_language"].reason())
        if AUTONOMOUS_MEDICATION_PATTERN.search(query):
            reasons.append(
                SAFETY_RULES["request_autonomous_medication_change"].reason()
            )
        if _has_medication_allergy_conflict(patient):
            reasons.append(SAFETY_RULES["medication_allergy_conflict"].reason())
        if not _has_core_context(patient):
            reasons.append(SAFETY_RULES["missing_core_context"].reason())
        if patient.truncated_categories:
            reasons.append(
                SAFETY_RULES["patient_context_truncated"].reason(
                    evidence_references=tuple(
                        f"patient:{category}"
                        for category in patient.truncated_categories
                    ),
                )
            )

        requires_review = bool(reasons)
        return SafetyResult(
            decision=(
                SafetyDecision.REVIEW if requires_review else SafetyDecision.PASS
            ),
            requires_human_review=requires_review,
            policy_version=SAFETY_PRECHECK_POLICY_VERSION,
            reasons=reasons,
        )

    async def evaluate_draft(
        self,
        *,
        query: str,
        draft: ResponseDraft,
        citations: list[Citation],
    ) -> SafetyResult:
        """Flag generated content that should not become a final answer as-is."""

        del query
        normalized_answer = " ".join(draft.answer.casefold().split())
        reasons: list[SafetyReason] = []
        if DIAGNOSIS_OR_PRESCRIBING_PATTERN.search(draft.answer):
            reasons.append(SAFETY_RULES["draft_diagnosis_or_prescribing"].reason())
        if AUTONOMOUS_MEDICATION_PATTERN.search(draft.answer):
            reasons.append(SAFETY_RULES["draft_autonomous_medication_change"].reason())
        if not citations or not any(
            phrase in normalized_answer
            for phrase in (
                "guideline",
                "guidelines",
                "evidence",
                "citation",
                "citations",
                "reference",
                "references",
            )
        ):
            reasons.append(SAFETY_RULES["draft_missing_grounding_signal"].reason())

        blocked = any(
            reason.code == "draft_diagnosis_or_prescribing" for reason in reasons
        )
        requires_review = bool(reasons) and not blocked
        return SafetyResult(
            decision=(
                SafetyDecision.BLOCK
                if blocked
                else SafetyDecision.REVIEW
                if requires_review
                else SafetyDecision.PASS
            ),
            requires_human_review=requires_review,
            policy_version=SAFETY_POST_GENERATION_POLICY_VERSION,
            reasons=reasons,
        )
