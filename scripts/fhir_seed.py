"""Safely seed and verify the local checksum-locked cohort in HAPI FHIR."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from scripts.synthetic_cohort import (
    CohortError,
    load_candidate,
    load_support_bundle,
    verify_local,
)

JsonObject = dict[str, Any]
RESOURCE_TYPE_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]+$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class FhirSeedError(RuntimeError):
    """Safe local FHIR seed or verification failure."""


@dataclass(frozen=True)
class LocalCohort:
    """Verified local cohort metadata required for seeding."""

    bundles: tuple[JsonObject, ...]
    patient_ids: tuple[str, ...]
    expected_counts: Mapping[str, int]


def validate_local_base_url(raw_url: str) -> str:
    """Return a canonical URL only for an explicit loopback /fhir endpoint."""

    parsed = urlsplit(raw_url)
    try:
        port = parsed.port
    except ValueError as error:
        raise FhirSeedError("FHIR base URL has an invalid port") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or port is None
        or not 1024 <= port <= 65535
        or parsed.path.rstrip("/") != "/fhir"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise FhirSeedError(
            "FHIR writes are restricted to http://localhost:<port>/fhir "
            "or http://127.0.0.1:<port>/fhir"
        )
    return f"http://{parsed.hostname}:{port}/fhir"


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FhirSeedError(f"{path.name}: invalid local JSON") from error
    if not isinstance(value, dict):
        raise FhirSeedError(f"{path.name}: expected a JSON object")
    return cast(JsonObject, value)


def load_local_cohort(manifest_path: Path, lock_path: Path) -> LocalCohort:
    """Validate ignored local files and collect unique expected resources."""

    try:
        verify_local(
            argparse.Namespace(
                manifest=str(manifest_path),
                lock=str(lock_path),
            )
        )
    except CohortError as error:
        raise FhirSeedError(str(error)) from error

    manifest = _read_json(manifest_path)
    raw_fixtures = manifest.get("fixtures")
    if not isinstance(raw_fixtures, list):
        raise FhirSeedError("invalid local cohort manifest")

    manifest_root = manifest_path.parent.resolve()
    bundles: list[JsonObject] = []
    patient_ids: list[str] = []
    resources: dict[tuple[str, str], JsonObject] = {}

    def add_resources(
        fixture_name: str,
        typed_resources: Mapping[str, Sequence[JsonObject]],
    ) -> None:
        for resource_type, resource_items in typed_resources.items():
            if not RESOURCE_TYPE_PATTERN.fullmatch(resource_type):
                raise FhirSeedError("invalid FHIR resource type")
            for resource in resource_items:
                resource_id = resource.get("id")
                if not isinstance(resource_id, str) or not resource_id:
                    raise FhirSeedError(f"{fixture_name}: resource without a stable ID")
                key = (resource_type, resource_id)
                previous = resources.get(key)
                if previous is not None and previous != resource:
                    raise FhirSeedError(
                        f"{fixture_name}: conflicting duplicate resource"
                    )
                resources[key] = resource

    raw_support_bundles = manifest.get("support_bundles")
    if not isinstance(raw_support_bundles, list):
        raise FhirSeedError("invalid local support Bundle metadata")
    for raw_support in raw_support_bundles:
        if not isinstance(raw_support, dict):
            raise FhirSeedError("invalid local support Bundle metadata")
        support = cast(JsonObject, raw_support)
        relative_path = support.get("path")
        raw_resource_counts = support.get("resource_counts")
        if not isinstance(relative_path, str) or not isinstance(
            raw_resource_counts, dict
        ):
            raise FhirSeedError("incomplete local support Bundle metadata")
        fixture_path = (manifest_root / relative_path).resolve()
        if not fixture_path.is_relative_to(manifest_root):
            raise FhirSeedError("fixture path escapes the synthetic data directory")
        expected_types = frozenset(
            key for key in raw_resource_counts if isinstance(key, str)
        )
        bundle = load_support_bundle(fixture_path, expected_types)
        bundles.append(bundle)
        support_resources: dict[str, list[JsonObject]] = {}
        for raw_entry in cast(list[object], bundle["entry"]):
            if not isinstance(raw_entry, dict):
                raise FhirSeedError("invalid local support Bundle entry")
            resource = raw_entry.get("resource")
            if not isinstance(resource, dict):
                raise FhirSeedError("invalid local support Bundle resource")
            typed_resource = cast(JsonObject, resource)
            resource_type = typed_resource.get("resourceType")
            if not isinstance(resource_type, str):
                raise FhirSeedError("support resource has no resource type")
            support_resources.setdefault(resource_type, []).append(typed_resource)
        add_resources(fixture_path.name, support_resources)

    for raw_fixture in raw_fixtures:
        if not isinstance(raw_fixture, dict):
            raise FhirSeedError("invalid local fixture metadata")
        fixture = cast(JsonObject, raw_fixture)
        relative_path = fixture.get("path")
        patient_id = fixture.get("patient_id")
        if not isinstance(relative_path, str) or not isinstance(patient_id, str):
            raise FhirSeedError("incomplete local fixture metadata")
        fixture_path = (manifest_root / relative_path).resolve()
        if not fixture_path.is_relative_to(manifest_root):
            raise FhirSeedError("fixture path escapes the synthetic data directory")
        candidate = load_candidate(fixture_path)
        if candidate is None:
            raise FhirSeedError(f"{fixture_path.name}: invalid transaction Bundle")
        bundles.append(candidate.bundle)
        patient_ids.append(patient_id)
        add_resources(fixture_path.name, candidate.resources)

    expected_counts = Counter(resource_type for resource_type, _ in resources)
    return LocalCohort(
        bundles=tuple(bundles),
        patient_ids=tuple(patient_ids),
        expected_counts=dict(sorted(expected_counts.items())),
    )


class FhirHttp:
    """Small write-only administration transport with safe error messages."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = validate_local_base_url(base_url)
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        url = f"{self.base_url}/" if not path else f"{self.base_url}/{path.lstrip('/')}"
        body = None
        headers = {
            "Accept": "application/fhir+json",
            "Cache-Control": "no-cache",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/fhir+json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except HTTPError as error:
            raise FhirSeedError(
                f"HAPI returned HTTP {error.code} for {method} "
                f"{path or '<transaction>'}"
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise FhirSeedError(
                f"HAPI is unavailable for {method} {path or '<transaction>'}"
            ) from error
        try:
            value = json.loads(raw_response)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FhirSeedError(
                f"HAPI returned invalid JSON for {method} {path or '<transaction>'}"
            ) from error
        if not isinstance(value, dict):
            raise FhirSeedError("HAPI returned a non-object JSON response")
        return cast(JsonObject, value)


def verify_server(http: FhirHttp) -> None:
    """Verify the target is the expected local HAPI FHIR R4 server."""

    metadata = http.request("GET", "metadata")
    software = metadata.get("software")
    software_name = software.get("name") if isinstance(software, dict) else None
    if (
        metadata.get("resourceType") != "CapabilityStatement"
        or metadata.get("fhirVersion") != "4.0.1"
        or software_name != "HAPI FHIR Server"
    ):
        raise FhirSeedError("target is not the expected HAPI FHIR R4 server")


def resource_counts(http: FhirHttp, resource_types: Sequence[str]) -> dict[str, int]:
    """Read exact server totals without returning patient resource content."""

    counts: dict[str, int] = {}
    for resource_type in resource_types:
        if not RESOURCE_TYPE_PATTERN.fullmatch(resource_type):
            raise FhirSeedError("invalid FHIR resource type")
        result = http.request(
            "GET",
            f"{quote(resource_type)}?_summary=count&_count=0",
        )
        total = result.get("total")
        if result.get("resourceType") != "Bundle" or not isinstance(total, int):
            raise FhirSeedError(f"HAPI returned no count for {resource_type}")
        counts[resource_type] = total
    return counts


def _verify_bundle_response(
    response: JsonObject,
    expected_entries: int,
    expected_type: str,
) -> tuple[int, int]:
    raw_entries = response.get("entry")
    if (
        response.get("resourceType") != "Bundle"
        or response.get("type") != f"{expected_type}-response"
        or not isinstance(raw_entries, list)
        or len(raw_entries) != expected_entries
    ):
        raise FhirSeedError("HAPI returned an incomplete Bundle response")

    created = 0
    updated = 0
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise FhirSeedError("HAPI returned an invalid Bundle response entry")
        raw_response = raw_entry.get("response")
        status = raw_response.get("status") if isinstance(raw_response, dict) else None
        if not isinstance(status, str) or not status.startswith("2"):
            raise FhirSeedError("HAPI Bundle response contained a failed entry")
        if status.startswith("201"):
            created += 1
        else:
            updated += 1
    return created, updated


def idempotent_transaction(bundle: JsonObject) -> JsonObject:
    """Convert generated patient POST entries to stable-ID PUT requests."""

    if bundle.get("type") != "transaction":
        return bundle
    transformed = copy.deepcopy(bundle)
    raw_entries = transformed.get("entry")
    if not isinstance(raw_entries, list):
        raise FhirSeedError("local transaction Bundle has no entries")
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise FhirSeedError("local transaction Bundle has an invalid entry")
        resource = raw_entry.get("resource")
        request = raw_entry.get("request")
        if not isinstance(resource, dict) or not isinstance(request, dict):
            raise FhirSeedError("local transaction Bundle has an incomplete entry")
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not isinstance(resource_type, str) or not isinstance(resource_id, str):
            raise FhirSeedError("local transaction resource has no stable ID")
        request["method"] = "PUT"
        request["url"] = f"{resource_type}/{resource_id}"
        request.pop("ifNoneExist", None)
    return transformed


def verify_seeded(http: FhirHttp, cohort: LocalCohort) -> None:
    """Verify exact resource totals and stable patient reads."""

    actual_counts = resource_counts(http, tuple(cohort.expected_counts))
    if actual_counts != dict(cohort.expected_counts):
        differences = ", ".join(
            f"{resource_type}: expected={expected}, "
            f"actual={actual_counts.get(resource_type, 0)}"
            for resource_type, expected in cohort.expected_counts.items()
            if actual_counts.get(resource_type) != expected
        )
        raise FhirSeedError(
            f"HAPI resource counts do not match the locked cohort ({differences}); "
            "run 'make fhir-reset CONFIRM=1' before retrying"
        )
    for patient_id in cohort.patient_ids:
        patient = http.request("GET", f"Patient/{quote(patient_id, safe='')}")
        if patient.get("resourceType") != "Patient" or patient.get("id") != patient_id:
            raise FhirSeedError("a locked synthetic patient is not queryable")

    summary = ", ".join(
        f"{resource_type}={count}"
        for resource_type, count in cohort.expected_counts.items()
    )
    print(f"Verified local HAPI cohort: {summary}")
    print(f"Verified stable synthetic patients: {len(cohort.patient_ids)}")


def seed(http: FhirHttp, cohort: LocalCohort) -> None:
    """Import the cohort only into an empty or exactly matching local server."""

    verify_server(http)
    actual_counts = resource_counts(http, tuple(cohort.expected_counts))
    expected_counts = dict(cohort.expected_counts)
    if any(actual_counts.values()) and actual_counts != expected_counts:
        raise FhirSeedError(
            "HAPI contains unexpected or partial data; "
            "run 'make fhir-reset CONFIRM=1' before seeding"
        )

    created = 0
    updated = 0
    for source_bundle in cohort.bundles:
        bundle = idempotent_transaction(source_bundle)
        raw_entries = bundle.get("entry")
        bundle_type = bundle.get("type")
        if not isinstance(raw_entries, list):
            raise FhirSeedError("local Bundle has no entries")
        if bundle_type not in {"batch", "transaction"}:
            raise FhirSeedError("local Bundle has an unsupported type")
        response = http.request("POST", "", bundle)
        bundle_created, bundle_updated = _verify_bundle_response(
            response,
            len(raw_entries),
            bundle_type,
        )
        created += bundle_created
        updated += bundle_updated

    print(f"HAPI transaction entries accepted: created={created}, updated={updated}")
    verify_seeded(http, cohort)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check-target", "seed", "verify", "verify-empty"),
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--lock")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a safe local HAPI administration command."""

    args = _parser().parse_args(argv)
    try:
        if args.timeout_seconds <= 0:
            raise FhirSeedError("timeout must be positive")
        http = FhirHttp(args.base_url, args.timeout_seconds)
        verify_server(http)
        if args.command == "check-target":
            print(f"Verified local HAPI target: {http.base_url}")
            return 0
        if not isinstance(args.manifest, str) or not isinstance(args.lock, str):
            raise FhirSeedError("manifest and lock are required")
        cohort = load_local_cohort(Path(args.manifest), Path(args.lock))
        if args.command == "seed":
            seed(http, cohort)
        elif args.command == "verify":
            verify_seeded(http, cohort)
        else:
            counts = resource_counts(http, tuple(cohort.expected_counts))
            if any(counts.values()):
                raise FhirSeedError("HAPI reset did not remove the local cohort")
            print("Verified empty local HAPI resource counts")
    except (FhirSeedError, CohortError) as error:
        print(f"FHIR seed error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
