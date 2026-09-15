"""Opt-in live Phase 4 grounded-provider generation gate."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

from httpx import AsyncClient, HTTPError, Response

from scripts.phase3_retrieval_live_gate import RetrievalLiveGateError, load_evaluation
from scripts.phase3_workflow_live_gate import DEFAULT_ALIAS, SUFFICIENT_CASE_ID

PROVIDER_FAILURE_CODES = {
    "response_generation_authentication_failed",
    "response_generation_context_limit",
    "response_generation_failed",
    "response_generation_invalid_input",
    "response_generation_invalid_output",
    "response_generation_rate_limited",
    "response_generation_refused",
    "response_generation_timeout",
    "response_generation_unavailable",
}
PHASE4_PROGRESS = {
    "4.1_grounded_generation": "complete",
    "4.2_safety_routing": "complete",
    "4.3_review_queue_actions": "complete",
    "4.4_concurrency_safe_resume": "complete",
    "4.5_phase_gate": "complete",
}


class GenerationLiveGateError(RuntimeError):
    """A live provider assertion failed without retaining sensitive payloads."""


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GenerationLiveGateError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _sequence(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise GenerationLiveGateError(f"{label} must be a JSON array")
    return value


def _patient_id(manifest_path: Path, alias: str) -> str:
    try:
        manifest = _mapping(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            label="cohort manifest",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GenerationLiveGateError("synthetic cohort manifest is invalid") from error
    for raw_fixture in _sequence(manifest.get("fixtures"), label="cohort fixtures"):
        fixture = _mapping(raw_fixture, label="cohort fixture")
        if fixture.get("alias") == alias:
            patient_id = fixture.get("patient_id")
            if isinstance(patient_id, str) and patient_id:
                return patient_id
    raise GenerationLiveGateError("selected synthetic cohort alias is unavailable")


async def _json(response: Response, *, expected_status: int) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise GenerationLiveGateError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected_status}"
        )
    try:
        return _mapping(response.json(), label="API response")
    except json.JSONDecodeError as error:
        raise GenerationLiveGateError("API response is not valid JSON") from error


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    return _mapping(payload.get("data"), label="API response data")


async def _create(
    client: AsyncClient,
    *,
    patient_id: str,
    query: str,
) -> dict[str, Any]:
    payload = await _json(
        await client.post(
            "/api/v1/workflows",
            json={"patient_id": patient_id, "query": query},
        ),
        expected_status=201,
    )
    serialized = json.dumps(payload, sort_keys=True)
    if patient_id in serialized or query in serialized:
        raise GenerationLiveGateError("workflow response exposed request content")
    return _data(payload)


def _citation_identity(value: object) -> tuple[str, str]:
    citation = _mapping(value, label="response citation")
    document_id = citation.get("document_id")
    chunk_id = citation.get("chunk_id")
    if not isinstance(document_id, str) or not isinstance(chunk_id, str):
        raise GenerationLiveGateError("response citation identity is invalid")
    return document_id, chunk_id


def validate_provider_workflow(
    workflow: dict[str, Any],
    *,
    expected_document_id: str,
    expected_chunk_id: str,
    expected_model: str | None = None,
) -> dict[str, object]:
    """Validate one live result and return its stable routing projection."""

    if (
        workflow.get("status") != "completed"
        or workflow.get("failure_code") is not None
    ):
        raise GenerationLiveGateError("provider-backed workflow did not complete")
    evidence = _mapping(workflow.get("guideline_evidence"), label="evidence summary")
    response = _mapping(workflow.get("final_response"), label="qualified response")
    answer = response.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise GenerationLiveGateError("structured provider answer is missing")
    disclaimer = response.get("disclaimer")
    if not isinstance(disclaimer, str) or "not medical advice" not in disclaimer:
        raise GenerationLiveGateError("application-owned disclaimer is missing")

    citations = _sequence(response.get("citations"), label="response citations")
    identities = [_citation_identity(item) for item in citations]
    document_ids = _sequence(
        evidence.get("document_ids"), label="evidence document IDs"
    )
    chunk_ids = _sequence(evidence.get("chunk_ids"), label="evidence chunk IDs")
    ordered_document_ids = list(dict.fromkeys(item[0] for item in identities))
    if (
        evidence.get("assessment") != "sufficient"
        or evidence.get("match_count") != len(citations)
        or not identities
        or ordered_document_ids != document_ids
        or [item[1] for item in identities] != chunk_ids
        or identities[0] != (expected_document_id, expected_chunk_id)
    ):
        raise GenerationLiveGateError(
            "provider result did not preserve application-owned citations"
        )

    transitions = [
        _mapping(item, label="transition").get("step")
        for item in _sequence(workflow.get("transitions"), label="transitions")
    ]
    if transitions[-1:] != ["finalize_response"]:
        raise GenerationLiveGateError("provider result bypassed finalization")
    audit = [
        _mapping(item, label="audit event")
        for item in _sequence(workflow.get("audit_log"), label="audit log")
    ]
    generation_events = [
        event for event in audit if event.get("event_type") == "response_generated"
    ]
    if len(generation_events) != 1:
        raise GenerationLiveGateError("provider generation audit event is missing")
    post_generation_safety_events = [
        event
        for event in audit
        if event.get("event_type") == "safety_evaluated"
        and _mapping(event.get("details"), label="safety audit").get("phase")
        == "post_generation"
    ]
    if len(post_generation_safety_events) != 1:
        raise GenerationLiveGateError("post-generation safety audit event is missing")
    safety_details = _mapping(
        post_generation_safety_events[0].get("details"),
        label="post-generation safety audit",
    )
    if (
        safety_details.get("decision") != "pass"
        or safety_details.get("policy_version") != "safety-post-generation-v1"
        or safety_details.get("reason_count") != 0
    ):
        raise GenerationLiveGateError(
            "post-generation safety audit metadata is invalid"
        )
    details = _mapping(generation_events[0].get("details"), label="generation audit")
    model_alias = details.get("model_alias")
    if (
        details.get("generator") != "provider"
        or details.get("outcome") != "success"
        or details.get("citation_count") != len(citations)
        or not isinstance(model_alias, str)
        or (expected_model is not None and model_alias != expected_model)
        or not isinstance(details.get("latency_ms"), int)
    ):
        raise GenerationLiveGateError("provider generation audit metadata is invalid")
    for field in ("input_tokens", "output_tokens"):
        value = details.get(field)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise GenerationLiveGateError("provider token audit metadata is invalid")

    serialized_audit = json.dumps(audit, sort_keys=True)
    forbidden_audit_values = [answer]
    for raw_citation in citations:
        citation = _mapping(raw_citation, label="response citation")
        forbidden_audit_values.extend(
            value
            for value in (citation.get("excerpt"), citation.get("source_url"))
            if isinstance(value, str)
        )
    if any(value in serialized_audit for value in forbidden_audit_values):
        raise GenerationLiveGateError("audit log retained provider or evidence content")

    return {
        "status": workflow.get("status"),
        "assessment": evidence.get("assessment"),
        "citation_identities": identities,
        "transitions": transitions,
        "audit_types": [event.get("event_type") for event in audit],
        "model_alias": model_alias,
        "phase_progress": PHASE4_PROGRESS,
    }


def validate_provider_failure(workflow: dict[str, Any]) -> None:
    """Assert that a provider failure cannot become an uncited fallback answer."""

    if (
        workflow.get("status") != "failed"
        or workflow.get("failure_code") not in PROVIDER_FAILURE_CODES
        or workflow.get("final_response") is not None
    ):
        raise GenerationLiveGateError("provider failure did not terminate safely")


async def run_gate(
    *,
    base_url: str,
    manifest_path: Path,
    evaluation_path: Path,
    alias: str,
    timeout_seconds: float,
    expected_model: str | None,
) -> dict[str, object]:
    """Run two synthetic provider calls and compare stable routing outcomes."""

    patient_id = _patient_id(manifest_path, alias)
    suite = load_evaluation(evaluation_path)
    cases = {case.case_id: case for case in suite.cases}
    case = cases.get(SUFFICIENT_CASE_ID)
    if (
        case is None
        or case.expected_document_id is None
        or case.expected_top_chunk_id is None
    ):
        raise GenerationLiveGateError("required retrieval evaluation case is missing")
    try:
        async with AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        ) as client:
            first = await _create(
                client,
                patient_id=patient_id,
                query=case.clinical_query,
            )
            first_projection = validate_provider_workflow(
                first,
                expected_document_id=case.expected_document_id,
                expected_chunk_id=case.expected_top_chunk_id,
                expected_model=expected_model,
            )
            workflow_id = first.get("workflow_id")
            if not isinstance(workflow_id, str):
                raise GenerationLiveGateError("completed workflow ID is missing")
            inspected = _data(
                await _json(
                    await client.get(f"/api/v1/workflows/{workflow_id}"),
                    expected_status=200,
                )
            )
            if inspected != first:
                raise GenerationLiveGateError("persisted provider result changed")

            second = await _create(
                client,
                patient_id=patient_id,
                query=case.clinical_query,
            )
            second_projection = validate_provider_workflow(
                second,
                expected_document_id=case.expected_document_id,
                expected_chunk_id=case.expected_top_chunk_id,
                expected_model=expected_model,
            )
            if second_projection != first_projection:
                raise GenerationLiveGateError(
                    "provider workflow routing is not reproducible"
                )
    except HTTPError as error:
        raise GenerationLiveGateError("live Phase 4 API request failed") from error

    identities = cast(list[tuple[str, str]], first_projection["citation_identities"])
    return {
        "fixture_alias": alias,
        "provider_model": first_projection["model_alias"],
        "provider_runs": 2,
        "routing_reproducible": True,
        "structured_answer": "verified",
        "citations_verified": len(identities),
        "qualification": "verified",
        "persistence": "verified",
        "redaction": "verified",
        "failure_no_fallback": "covered_by_deterministic_gate",
        "phase_progress": PHASE4_PROGRESS,
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
    parser.add_argument("--expected-model")
    parser.add_argument("--timeout-seconds", type=float, default=120)
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
                expected_model=args.expected_model,
            )
        )
    except (GenerationLiveGateError, RetrievalLiveGateError, ValueError) as error:
        print(f"Phase 4 generation live gate failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
