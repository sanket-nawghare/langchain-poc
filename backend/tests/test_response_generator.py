"""Deterministic qualified-response boundary tests."""

import pytest

from app.domain.clinical import Citation, ClinicalRecordSummary, PatientSummary
from app.domain.generation import GroundedGenerationRequest
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.grounded_generation import build_grounded_generation_request


def patient_summary() -> PatientSummary:
    return PatientSummary(
        patient_id="synthetic-patient-1",
        conditions=[
            ClinicalRecordSummary(
                code="private-code",
                display="Private synthetic condition",
            )
        ],
    )


@pytest.mark.anyio
def grounded_request(query: str) -> GroundedGenerationRequest:
    return build_grounded_generation_request(
        query=query,
        patient=patient_summary(),
        guidelines=[
            Citation(
                document_id="guideline-1",
                chunk_id="chunk-1",
                title="Synthetic guideline",
                publisher="Example publisher",
                source_url="https://example.test/guideline",
                excerpt="Trusted bounded evidence.",
            )
        ],
    )


@pytest.mark.anyio
async def test_deterministic_draft_uses_only_bounded_request_metadata() -> None:
    generator = DeterministicResponseGenerator()

    result = await generator.generate(
        request=grounded_request("private query marker"),
    )

    assert "1 curated guideline reference(s) are available" in result.draft.answer
    assert "patient-specific clinical guidance" in result.draft.answer
    assert "private query marker" not in result.draft.answer
    assert "Private synthetic condition" not in result.draft.answer
    assert "private-code" not in result.draft.answer
    assert result.metadata.generator == "deterministic"


@pytest.mark.anyio
async def test_deterministic_draft_replays_identically() -> None:
    generator = DeterministicResponseGenerator()

    request = grounded_request("What educational context is available?")
    first = await generator.generate(request=request)
    second = await generator.generate(request=request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
