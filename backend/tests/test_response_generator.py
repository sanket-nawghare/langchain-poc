"""Deterministic qualified-response boundary tests."""

import pytest

from app.domain.clinical import ClinicalRecordSummary, PatientSummary
from app.services.deterministic_response import DeterministicResponseGenerator


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
async def test_deterministic_draft_states_missing_guideline_evidence() -> None:
    generator = DeterministicResponseGenerator()

    draft = await generator.generate(
        query="private query marker",
        patient=patient_summary(),
        guidelines=[],
    )

    assert "No curated guideline evidence is available" in draft.answer
    assert "patient-specific clinical guidance" in draft.answer
    assert "private query marker" not in draft.answer
    assert "Private synthetic condition" not in draft.answer
    assert "private-code" not in draft.answer


@pytest.mark.anyio
async def test_deterministic_draft_replays_identically() -> None:
    generator = DeterministicResponseGenerator()

    first = await generator.generate(
        query="What educational context is available?",
        patient=patient_summary(),
        guidelines=[],
    )
    second = await generator.generate(
        query="What educational context is available?",
        patient=patient_summary(),
        guidelines=[],
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
