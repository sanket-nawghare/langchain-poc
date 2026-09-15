"""Phase 4 real-provider live-gate contract tests."""

from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.phase4_generation_live_gate import (
    PHASE4_PROGRESS,
    GenerationLiveGateError,
    validate_provider_failure,
    validate_provider_workflow,
)


def completed_snapshot() -> dict[str, object]:
    citation = {
        "document_id": "who-guideline",
        "chunk_id": "who-guideline.0",
        "title": "Reviewed guideline",
        "publisher": "who",
        "source_url": "https://example.test/guideline",
        "page": 4,
        "excerpt": "Bounded cited excerpt.",
    }
    return {
        "status": "completed",
        "failure_code": None,
        "guideline_evidence": {
            "assessment": "sufficient",
            "match_count": 1,
            "document_ids": ["who-guideline"],
            "chunk_ids": ["who-guideline.0"],
        },
        "final_response": {
            "answer": "Provider-generated bounded educational answer.",
            "citations": [citation],
            "disclaimer": "Educational demonstration; not medical advice.",
        },
        "transitions": [
            {"step": "begin_execution"},
            {"step": "finalize_response"},
        ],
        "audit_log": [
            {"event_type": "status_changed", "details": {}},
            {"event_type": "tool_called", "details": {}},
            {"event_type": "tool_called", "details": {}},
            {"event_type": "tool_called", "details": {}},
            {"event_type": "safety_evaluated", "details": {}},
            {
                "event_type": "response_generated",
                "details": {
                    "generator": "provider",
                    "outcome": "success",
                    "citation_count": 1,
                    "model_alias": "gpt-5.6-luna",
                    "latency_ms": 12,
                    "input_tokens": 100,
                    "output_tokens": 30,
                },
            },
            {
                "event_type": "safety_evaluated",
                "details": {
                    "phase": "post_generation",
                    "decision": "pass",
                    "policy_version": "safety-post-generation-v1",
                    "reason_count": 0,
                },
            },
            {"event_type": "status_changed", "details": {}},
        ],
    }


def test_live_gate_accepts_structured_cited_provider_result() -> None:
    projection = validate_provider_workflow(
        completed_snapshot(),
        expected_document_id="who-guideline",
        expected_chunk_id="who-guideline.0",
        expected_model="gpt-5.6-luna",
    )

    assert projection["model_alias"] == "gpt-5.6-luna"
    assert projection["citation_identities"] == [("who-guideline", "who-guideline.0")]
    assert projection["phase_progress"] == PHASE4_PROGRESS
    assert set(PHASE4_PROGRESS.values()) == {"complete"}


@pytest.mark.parametrize(
    "mutation",
    ["citation", "generator", "model", "audit_body", "answer"],
)
def test_live_gate_rejects_untrusted_or_inconsistent_result(mutation: str) -> None:
    snapshot = cast(dict[str, Any], deepcopy(completed_snapshot()))
    if mutation == "citation":
        snapshot["final_response"]["citations"][0]["chunk_id"] = "fabricated"
    elif mutation == "generator":
        snapshot["audit_log"][5]["details"]["generator"] = "deterministic"
    elif mutation == "model":
        snapshot["audit_log"][5]["details"]["model_alias"] = "unexpected"
    elif mutation == "audit_body":
        snapshot["audit_log"][5]["details"]["body"] = snapshot["final_response"][
            "answer"
        ]
    else:
        snapshot["final_response"]["answer"] = ""

    with pytest.raises(GenerationLiveGateError):
        validate_provider_workflow(
            snapshot,
            expected_document_id="who-guideline",
            expected_chunk_id="who-guideline.0",
            expected_model="gpt-5.6-luna",
        )


def test_provider_failure_cannot_return_a_fallback_answer() -> None:
    validate_provider_failure(
        {
            "status": "failed",
            "failure_code": "response_generation_rate_limited",
            "final_response": None,
        }
    )

    with pytest.raises(GenerationLiveGateError):
        validate_provider_failure(
            {
                "status": "completed",
                "failure_code": None,
                "final_response": {
                    "answer": "Uncited deterministic fallback",
                    "citations": [],
                },
            }
        )
