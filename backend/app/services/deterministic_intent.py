"""Deterministic local intent classifier for the Phase 2 workflow."""

import re

from app.domain.workflow import Intent, IntentClassification

CLINICAL_QA_TERMS = frozenset(
    {
        "allergy",
        "allergies",
        "clinical",
        "condition",
        "conditions",
        "guideline",
        "guidelines",
        "lab",
        "labs",
        "medication",
        "medications",
        "observation",
        "observations",
        "precaution",
        "precautions",
        "procedure",
        "procedures",
        "symptom",
        "symptoms",
    }
)
UNSUPPORTED_INTENT_TERMS = frozenset(
    {
        "appointment",
        "book",
        "cancel",
        "prescribe",
        "prescription",
        "refill",
        "reschedule",
        "schedule",
    }
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class DeterministicIntentClassifier:
    """Conservative keyword classifier with an explicit unknown fallback."""

    async def classify(self, query: str) -> IntentClassification:
        """Classify supported clinical QA only when no unsupported term appears."""

        tokens = frozenset(TOKEN_PATTERN.findall(query.casefold()))
        has_unsupported_term = bool(tokens & UNSUPPORTED_INTENT_TERMS)
        has_clinical_term = bool(tokens & CLINICAL_QA_TERMS)
        intent = (
            Intent.CLINICAL_QA
            if has_clinical_term and not has_unsupported_term
            else Intent.UNKNOWN
        )
        return IntentClassification(intent=intent)
