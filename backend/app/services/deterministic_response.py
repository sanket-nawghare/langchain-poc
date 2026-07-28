"""Deterministic educational response generator for local development."""

from app.domain.clinical import Citation, PatientSummary
from app.domain.workflow import ResponseDraft


class DeterministicResponseGenerator:
    """Return a stable draft without a model call or fabricated evidence."""

    async def generate(
        self,
        *,
        query: str,
        patient: PatientSummary,
        guidelines: list[Citation],
    ) -> ResponseDraft:
        """Describe the evidence boundary without reproducing input content."""

        del query, patient
        if guidelines:
            evidence_statement = (
                f"{len(guidelines)} curated guideline reference(s) are available."
            )
        else:
            evidence_statement = (
                "No curated guideline evidence is available in this phase."
            )
        return ResponseDraft(
            answer=(
                "The normalized synthetic patient context passed the initial "
                "deterministic safety pre-check. "
                f"{evidence_statement} This educational result does not provide "
                "patient-specific clinical guidance; consult a qualified "
                "healthcare professional."
            )
        )
