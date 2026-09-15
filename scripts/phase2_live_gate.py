"""Opt-in live Phase 2 workflow gate over checksum-locked synthetic data."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

from httpx import AsyncClient, HTTPError, Response

DEFAULT_ALIAS = "sparse-control-01"
SUPPORTED_QUERY = "What precautions relate to this patient conditions?"
URGENT_QUERY = "What precautions apply to chest pain?"
UNSUPPORTED_QUERY = "Please schedule an appointment"


class LiveGateError(RuntimeError):
    """A live Phase 2 assertion failed."""


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LiveGateError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _load_patient_id(manifest_path: Path, alias: str) -> str:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fixtures = _mapping(manifest, label="cohort manifest").get("fixtures")
    except (OSError, json.JSONDecodeError) as error:
        raise LiveGateError("could not read the synthetic cohort manifest") from error
    if not isinstance(fixtures, list):
        raise LiveGateError("cohort manifest fixtures are invalid")
    for raw_fixture in fixtures:
        fixture = _mapping(raw_fixture, label="cohort fixture")
        if fixture.get("alias") == alias:
            patient_id = fixture.get("patient_id")
            if isinstance(patient_id, str) and patient_id:
                return patient_id
    raise LiveGateError(f"synthetic cohort alias is unavailable: {alias}")


async def _json(response: Response, *, expected_status: int) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise LiveGateError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected_status}"
        )
    try:
        return _mapping(response.json(), label="API response")
    except json.JSONDecodeError as error:
        raise LiveGateError("API response is not valid JSON") from error


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    return _mapping(payload.get("data"), label="API response data")


async def _create(
    client: AsyncClient,
    *,
    patient_id: str,
    query: str,
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/workflows",
        json={"patient_id": patient_id, "query": query},
    )
    payload = await _json(response, expected_status=201)
    serialized = json.dumps(payload, sort_keys=True)
    if patient_id in serialized or query in serialized:
        raise LiveGateError("workflow response exposed redacted request content")
    return _data(payload), serialized


async def run_gate(
    *,
    base_url: str,
    manifest_path: Path,
    alias: str,
    timeout_seconds: float,
) -> dict[str, str]:
    """Exercise seeded success, safety, rejection, and failure routes."""

    patient_id = _load_patient_id(manifest_path, alias)
    try:
        async with AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        ) as client:
            summary_response = await client.get(
                f"/api/v1/patients/{patient_id}/summary"
            )
            summary = _data(await _json(summary_response, expected_status=200))
            if summary.get("truncated_categories") != []:
                raise LiveGateError("selected patient summary is truncated")

            completed, _ = await _create(
                client,
                patient_id=patient_id,
                query=SUPPORTED_QUERY,
            )
            if completed.get("status") != "completed":
                raise LiveGateError("supported workflow did not complete")
            final_response = _mapping(
                completed.get("final_response"),
                label="qualified response",
            )
            if final_response.get("citations") != []:
                raise LiveGateError("Phase 2 response fabricated guideline citations")
            disclaimer = final_response.get("disclaimer")
            if (
                not isinstance(disclaimer, str)
                or "not medical advice" not in disclaimer
            ):
                raise LiveGateError("qualified response disclaimer is missing")
            transition_steps = [
                _mapping(item, label="transition").get("step")
                for item in cast(list[object], completed.get("transitions"))
            ]
            if transition_steps != ["begin_execution", "generate_response"]:
                raise LiveGateError("completed transition history is unexpected")
            audit_types = [
                _mapping(item, label="audit event").get("event_type")
                for item in cast(list[object], completed.get("audit_log"))
            ]
            if audit_types != [
                "status_changed",
                "tool_called",
                "tool_called",
                "safety_evaluated",
                "response_generated",
                "status_changed",
            ]:
                raise LiveGateError("completed audit history is unexpected")

            workflow_id = completed.get("workflow_id")
            if not isinstance(workflow_id, str):
                raise LiveGateError("completed workflow ID is missing")
            inspected = _data(
                await _json(
                    await client.get(f"/api/v1/workflows/{workflow_id}"),
                    expected_status=200,
                )
            )
            if inspected != completed:
                raise LiveGateError("persisted workflow snapshot changed on inspection")

            review, _ = await _create(
                client,
                patient_id=patient_id,
                query=URGENT_QUERY,
            )
            if (
                review.get("status") != "pending_review"
                or review.get("requires_human_review") is not True
                or review.get("final_response") is not None
            ):
                raise LiveGateError("urgent workflow did not stop for review")

            rejected, _ = await _create(
                client,
                patient_id=patient_id,
                query=UNSUPPORTED_QUERY,
            )
            if rejected.get("status") != "rejected":
                raise LiveGateError("unsupported workflow was not rejected")

            missing, missing_serialized = await _create(
                client,
                patient_id="phase2-missing-patient",
                query=SUPPORTED_QUERY,
            )
            if (
                missing.get("status") != "failed"
                or missing.get("failure_code") != "patient_not_found"
                or "phase2-missing-patient" in missing_serialized
            ):
                raise LiveGateError("missing patient did not fail safely")

            invalid_query = "private invalid query marker"
            invalid_response = await client.post(
                "/api/v1/workflows",
                json={
                    "patient_id": "invalid/patient",
                    "query": invalid_query,
                },
            )
            invalid_payload = await _json(invalid_response, expected_status=400)
            if _mapping(invalid_payload.get("error"), label="API error").get(
                "code"
            ) != "invalid_workflow_request" or invalid_query in json.dumps(
                invalid_payload
            ):
                raise LiveGateError("invalid workflow request was not redacted")
    except HTTPError as error:
        raise LiveGateError("live Phase 2 API request failed") from error

    return {
        "fixture_alias": alias,
        "happy_path": "completed",
        "safety_path": "pending_review",
        "unsupported_path": "rejected",
        "missing_patient_path": "failed",
        "invalid_request_path": "rejected_before_execution",
        "persistence": "verified",
        "redaction": "verified",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/synthetic/cohort-manifest.json"),
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
                alias=args.alias,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except LiveGateError as error:
        print(f"Phase 2 live gate failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
