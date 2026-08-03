"""Phase 3 cited-workflow live-gate contract tests."""

from copy import deepcopy
from typing import Any, cast

import pytest
from scripts.phase3_workflow_live_gate import (
    WorkflowLiveGateError,
    _restart_recovery_gate,
    validate_completed_workflow,
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
    audit = [
        {"details": {"step": "begin_execution"}},
        {"details": {"tool": "intent_classifier"}},
        {"details": {"tool": "patient_summary_reader"}},
        {
            "details": {
                "tool": "guideline_retriever",
                "assessment": "sufficient",
                "match_count": 1,
            }
        },
        {"details": {"decision": "pass"}},
        {"details": {"citation_count": 1}},
        {"details": {"step": "generate_response"}},
    ]
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
            "answer": "Bounded educational answer.",
            "citations": [citation],
            "disclaimer": "Educational demonstration; not medical advice.",
        },
        "transitions": [
            {"step": "begin_execution"},
            {"step": "generate_response"},
        ],
        "audit_log": audit,
    }


def test_completed_gate_requires_exact_resolvable_citation_identity() -> None:
    count = validate_completed_workflow(
        completed_snapshot(),
        expected_document_id="who-guideline",
        expected_chunk_id="who-guideline.0",
    )

    assert count == 1


@pytest.mark.parametrize("field", ["citation", "summary", "missing"])
def test_completed_gate_rejects_inconsistent_evidence(field: str) -> None:
    snapshot = cast(dict[str, Any], deepcopy(completed_snapshot()))
    if field == "citation":
        snapshot["final_response"]["citations"][0]["chunk_id"] = "wrong"
    elif field == "summary":
        snapshot["guideline_evidence"]["chunk_ids"] = ["wrong"]
    else:
        snapshot["final_response"]["citations"] = []

    with pytest.raises(WorkflowLiveGateError):
        validate_completed_workflow(
            snapshot,
            expected_document_id="who-guideline",
            expected_chunk_id="who-guideline.0",
        )


@pytest.mark.anyio
async def test_restart_recovery_gate_uses_no_clinical_replay() -> None:
    await _restart_recovery_gate()
