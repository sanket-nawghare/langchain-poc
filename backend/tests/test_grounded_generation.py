"""Minimum-necessary grounded generation request tests."""

import pytest

from app.domain.clinical import Citation, ClinicalRecordSummary, PatientSummary
from app.domain.generation import MAX_GROUNDED_FACTS
from app.services.grounded_generation import build_grounded_generation_request
from app.tools.response import ResponseGenerationMalformedOutputError


def citation(rank: int, *, excerpt: str | None = None) -> Citation:
    return Citation(
        document_id=f"guideline-{rank}",
        chunk_id=f"chunk-{rank}",
        title=f"Synthetic guideline {rank}",
        publisher="Example publisher",
        source_url=f"https://example.test/guideline/{rank}",
        page=rank,
        excerpt=excerpt or f"Bounded evidence {rank}.",
    )


def patient(*, truncated: bool = False) -> PatientSummary:
    return PatientSummary(
        patient_id="synthetic-private-id",
        display_name="Private Display Name",
        conditions=[
            ClinicalRecordSummary(
                code=f"private-code-{index}",
                display=(
                    "Asthma relevant condition"
                    if index == 39
                    else f"Synthetic condition {index}"
                ),
                status="active",
            )
            for index in range(40)
        ],
        truncated_categories=["conditions"] if truncated else [],
    )


def citation_without_excerpt() -> Citation:
    return citation(1).model_copy(update={"excerpt": None})


def test_selector_bounds_and_prioritizes_patient_facts_without_identifiers() -> None:
    request = build_grounded_generation_request(
        query="What precautions apply to asthma?",
        patient=patient(),
        guidelines=[citation(1)],
    )

    assert len(request.patient_context.facts) == MAX_GROUNDED_FACTS
    assert request.patient_context.facts[0].display == "Asthma relevant condition"
    serialized = request.model_dump_json()
    assert "synthetic-private-id" not in serialized
    assert "Private Display Name" not in serialized
    assert "private-code" not in serialized


def test_selector_preserves_exact_ranked_evidence() -> None:
    citations = [citation(1), citation(2)]

    request = build_grounded_generation_request(
        query="What precautions apply?",
        patient=patient(),
        guidelines=citations,
    )

    assert [item.rank for item in request.evidence] == [1, 2]
    assert [item.citation for item in request.evidence] == citations


@pytest.mark.parametrize(
    ("query", "summary", "guidelines"),
    [
        ("Mention synthetic-private-id", patient(), [citation(1)]),
        ("Mention Private Display Name", patient(), [citation(1)]),
        ("What precautions apply?", patient(truncated=True), [citation(1)]),
        ("What precautions apply?", patient(), []),
        ("What precautions apply?", patient(), [citation_without_excerpt()]),
    ],
)
def test_selector_rejects_unsafe_or_incomplete_context(
    query: str,
    summary: PatientSummary,
    guidelines: list[Citation],
) -> None:
    with pytest.raises(ResponseGenerationMalformedOutputError):
        build_grounded_generation_request(
            query=query,
            patient=summary,
            guidelines=guidelines,
        )
