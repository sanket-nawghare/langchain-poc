"""Deterministic educational response generator for local development."""

from app.domain.generation import (
    GroundedGenerationRequest,
    ResponseGenerationMetadata,
    ResponseGenerationResult,
)
from app.domain.workflow import ResponseDraft


class DeterministicResponseGenerator:
    """Return a stable draft without a model call or fabricated evidence."""

    async def generate(
        self,
        *,
        request: GroundedGenerationRequest,
    ) -> ResponseGenerationResult:
        """Describe the evidence boundary without reproducing input content."""

        return ResponseGenerationResult(
            draft=ResponseDraft(
                answer=(
                    "The normalized synthetic patient context passed the initial "
                    "deterministic safety pre-check. "
                    f"{len(request.evidence)} curated guideline reference(s) are "
                    "available. This educational result does not provide "
                    "patient-specific clinical guidance; consult a qualified "
                    "healthcare professional."
                )
            ),
            metadata=ResponseGenerationMetadata(generator="deterministic"),
        )
