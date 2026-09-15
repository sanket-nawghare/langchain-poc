"""Opt-in live Phase 3 cited-workflow and persistence gate."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import uuid4

from httpx import AsyncClient, HTTPError, Response

from app.api.workflows import create_workflow_run_service
from app.domain.workflow import WorkflowRunSnapshot
from app.services.sqlite_workflow_runs import SqliteWorkflowRunStore
from scripts.phase3_retrieval_live_gate import RetrievalLiveGateError, load_evaluation

DEFAULT_ALIAS = "sparse-control-01"
SUFFICIENT_CASE_ID = "hypertension-target"
INSUFFICIENT_CASE_ID = "unrelated-fracture"
UNSUPPORTED_QUERY = "Please schedule an appointment"


class WorkflowLiveGateError(RuntimeError):
    """A live Phase 3 workflow assertion failed without retaining payloads."""


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowLiveGateError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _sequence(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkflowLiveGateError(f"{label} must be a JSON array")
    return value


def _patient_id(manifest_path: Path, alias: str) -> str:
    try:
        manifest = _mapping(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            label="cohort manifest",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkflowLiveGateError("synthetic cohort manifest is invalid") from error
    for raw_fixture in _sequence(manifest.get("fixtures"), label="cohort fixtures"):
        fixture = _mapping(raw_fixture, label="cohort fixture")
        if fixture.get("alias") == alias:
            patient_id = fixture.get("patient_id")
            if isinstance(patient_id, str) and patient_id:
                return patient_id
    raise WorkflowLiveGateError("selected synthetic cohort alias is unavailable")


async def _json(response: Response, *, expected_status: int) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise WorkflowLiveGateError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected_status}"
        )
    try:
        return _mapping(response.json(), label="API response")
    except json.JSONDecodeError as error:
        raise WorkflowLiveGateError("API response is not valid JSON") from error


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    return _mapping(payload.get("data"), label="API response data")


async def _create(
    client: AsyncClient,
    *,
    patient_id: str,
    query: str,
) -> tuple[dict[str, Any], str]:
    payload = await _json(
        await client.post(
            "/api/v1/workflows",
            json={"patient_id": patient_id, "query": query},
        ),
        expected_status=201,
    )
    serialized = json.dumps(payload, sort_keys=True)
    if patient_id in serialized or query in serialized:
        raise WorkflowLiveGateError("workflow response exposed request content")
    return _data(payload), serialized


def validate_completed_workflow(
    workflow: dict[str, Any],
    *,
    expected_document_id: str,
    expected_chunk_id: str,
) -> int:
    """Validate a completed snapshot and return its citation count."""

    if (
        workflow.get("status") != "completed"
        or workflow.get("failure_code") is not None
    ):
        raise WorkflowLiveGateError("sufficient workflow did not complete")
    evidence = _mapping(workflow.get("guideline_evidence"), label="evidence summary")
    response = _mapping(workflow.get("final_response"), label="qualified response")
    citations = _sequence(response.get("citations"), label="response citations")
    if (
        evidence.get("assessment") != "sufficient"
        or evidence.get("match_count") != len(citations)
        or not citations
    ):
        raise WorkflowLiveGateError("completed evidence summary is inconsistent")
    top = _mapping(citations[0], label="top citation")
    if (
        top.get("document_id") != expected_document_id
        or top.get("chunk_id") != expected_chunk_id
        or not isinstance(top.get("source_url"), str)
        or not isinstance(top.get("excerpt"), str)
    ):
        raise WorkflowLiveGateError("completed citation does not resolve as expected")
    document_ids = _sequence(
        evidence.get("document_ids"), label="evidence document IDs"
    )
    chunk_ids = _sequence(evidence.get("chunk_ids"), label="evidence chunk IDs")
    if (
        not document_ids
        or not chunk_ids
        or document_ids[0] != expected_document_id
        or chunk_ids[0] != expected_chunk_id
    ):
        raise WorkflowLiveGateError("evidence and citation identities differ")
    disclaimer = response.get("disclaimer")
    if not isinstance(disclaimer, str) or "not medical advice" not in disclaimer:
        raise WorkflowLiveGateError("qualified response disclaimer is missing")
    transition_steps = [
        _mapping(item, label="transition").get("step")
        for item in _sequence(workflow.get("transitions"), label="transitions")
    ]
    if transition_steps != ["begin_execution", "generate_response"]:
        raise WorkflowLiveGateError("completed transition history is unexpected")
    audit = _sequence(workflow.get("audit_log"), label="audit log")
    retrieval_events = [
        _mapping(item, label="audit event")
        for item in audit
        if _mapping(item, label="audit event").get("details", {}).get("tool")
        == "guideline_retriever"
    ]
    if len(audit) != 7 or len(retrieval_events) != 1:
        raise WorkflowLiveGateError("completed audit history is unexpected")
    return len(citations)


async def _restart_recovery_gate() -> None:
    """Verify an interrupted checkpoint fails without replay or clinical data."""

    with TemporaryDirectory(prefix="phase3-recovery-") as directory:
        store = SqliteWorkflowRunStore(f"sqlite:///{Path(directory) / 'runs.db'}")
        await store.initialize()
        now = datetime.now(UTC)
        queued = WorkflowRunSnapshot.queued(
            workflow_id=uuid4(),
            correlation_id=uuid4(),
            trace_id=uuid4(),
            created_at=now,
        )
        await store.save(queued)
        recovered_count = await create_workflow_run_service(store).recover_interrupted()
        recovered = await store.get(queued.workflow_id)
        if (
            recovered_count != 1
            or recovered is None
            or recovered.status.value != "failed"
            or recovered.failure_code != "workflow_interrupted"
            or recovered.final_response is not None
        ):
            raise WorkflowLiveGateError("restart recovery did not fail safely")


async def run_gate(
    *,
    base_url: str,
    manifest_path: Path,
    evaluation_path: Path,
    alias: str,
    timeout_seconds: float,
) -> dict[str, object]:
    """Exercise live cited, weak-evidence, persistence, and recovery paths."""

    patient_id = _patient_id(manifest_path, alias)
    suite = load_evaluation(evaluation_path)
    cases = {case.case_id: case for case in suite.cases}
    sufficient_case = cases.get(SUFFICIENT_CASE_ID)
    insufficient_case = cases.get(INSUFFICIENT_CASE_ID)
    if (
        sufficient_case is None
        or sufficient_case.expected_document_id is None
        or sufficient_case.expected_top_chunk_id is None
        or insufficient_case is None
    ):
        raise WorkflowLiveGateError("required retrieval evaluation cases are missing")
    try:
        async with AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        ) as client:
            completed, _ = await _create(
                client,
                patient_id=patient_id,
                query=sufficient_case.clinical_query,
            )
            citation_count = validate_completed_workflow(
                completed,
                expected_document_id=sufficient_case.expected_document_id,
                expected_chunk_id=sufficient_case.expected_top_chunk_id,
            )
            workflow_id = completed.get("workflow_id")
            if not isinstance(workflow_id, str):
                raise WorkflowLiveGateError("completed workflow ID is missing")
            inspected = _data(
                await _json(
                    await client.get(f"/api/v1/workflows/{workflow_id}"),
                    expected_status=200,
                )
            )
            if inspected != completed:
                raise WorkflowLiveGateError("persisted cited snapshot changed")

            review, _ = await _create(
                client,
                patient_id=patient_id,
                query=insufficient_case.clinical_query,
            )
            evidence = _mapping(
                review.get("guideline_evidence"), label="review evidence"
            )
            if (
                review.get("status") != "pending_review"
                or review.get("requires_human_review") is not True
                or review.get("final_response") is not None
                or evidence.get("assessment") != "insufficient"
                or evidence.get("match_count") != 0
            ):
                raise WorkflowLiveGateError("weak evidence did not pause safely")

            rejected, _ = await _create(
                client,
                patient_id=patient_id,
                query=UNSUPPORTED_QUERY,
            )
            if rejected.get("status") != "rejected":
                raise WorkflowLiveGateError("unsupported workflow was not rejected")
    except HTTPError as error:
        raise WorkflowLiveGateError("live Phase 3 API request failed") from error

    await _restart_recovery_gate()
    return {
        "fixture_alias": alias,
        "happy_path": "completed",
        "citations_verified": citation_count,
        "weak_evidence_path": "pending_review",
        "unsupported_path": "rejected",
        "persistence": "verified",
        "restart_recovery": "verified",
        "redaction": "verified",
        "policy_version": suite.policy_version,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/synthetic/cohort-manifest.json"),
    )
    parser.add_argument(
        "--evaluation",
        type=Path,
        default=Path("data/guidelines/retrieval-evaluation.json"),
    )
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(
            run_gate(
                base_url=args.base_url,
                manifest_path=args.manifest,
                evaluation_path=args.evaluation,
                alias=args.alias,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except (RetrievalLiveGateError, WorkflowLiveGateError, ValueError) as error:
        print(f"Phase 3 workflow live gate failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
