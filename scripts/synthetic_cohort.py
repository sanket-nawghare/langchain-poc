"""Generate metadata and select reviewed synthetic FHIR cohort fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

JsonObject = dict[str, Any]
Predicate = Callable[["Candidate"], bool]

MAX_FIXTURE_BYTES = 8 * 1024 * 1024
MAX_FIXTURE_ENTRIES = 1000
MAX_COHORT_BYTES = 24 * 1024 * 1024
EXPECTED_CANDIDATES = 100

FORBIDDEN_RESOURCE_TYPES = {
    "Binary",
    "DocumentReference",
    "Media",
}
SECRET_MARKERS = (
    "-----begin private key-----",
    "authorization: bearer",
    "api_key=",
    "apikey=",
)

TYPE_2_DIABETES_CODES = {"44054006"}
GLUCOSE_OBSERVATION_CODES = {
    "2339-0",
    "2345-7",
    "4548-4",
    "17856-6",
}
HYPERTENSION_CODES = {
    "38341003",
    "59621000",
}
BLOOD_PRESSURE_CODES = {
    "85354-9",
    "8480-6",
    "8462-4",
}
RESPIRATORY_CONDITION_CODES = {
    "13645005",
    "195967001",
    "233678006",
}
RESPIRATORY_TERMS = (
    "asthma",
    "chronic obstructive",
    "copd",
    "bronch",
    "albuterol",
    "inhal",
)
METABOLIC_MEDICATION_TERMS = (
    "glimepiride",
    "glipizide",
    "insulin",
    "metformin",
)
CARDIOVASCULAR_MEDICATION_TERMS = (
    "amlodipine",
    "atenolol",
    "hydrochlorothiazide",
    "lisinopril",
    "losartan",
    "metoprolol",
    "valsartan",
)


class CohortError(RuntimeError):
    """Safe cohort validation or selection failure."""


@dataclass(frozen=True)
class Candidate:
    """One validated Synthea patient transaction Bundle."""

    path: Path
    bundle: JsonObject
    patient_id: str
    resources: dict[str, list[JsonObject]]
    size_bytes: int
    entry_count: int


@dataclass(frozen=True)
class Scenario:
    """Deterministic fixture-selection rule."""

    alias: str
    predicate: Predicate
    evidence_types: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> JsonObject:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CohortError(f"{path.name}: invalid UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise CohortError(f"{path.name}: expected a JSON object")
    return cast(JsonObject, parsed)


def _write_json(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(value, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def _resource_type(resource: JsonObject) -> str:
    value = resource.get("resourceType")
    return value if isinstance(value, str) else ""


def _resource_id(resource: JsonObject) -> str:
    value = resource.get("id")
    return value if isinstance(value, str) else ""


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _coding_tuples(resource: JsonObject) -> set[tuple[str, str, str]]:
    codings: set[tuple[str, str, str]] = set()
    for value in _walk(resource):
        if not isinstance(value, dict):
            continue
        code = value.get("code")
        if not isinstance(code, str):
            continue
        system = value.get("system")
        display = value.get("display")
        codings.add(
            (
                system if isinstance(system, str) else "",
                code,
                display if isinstance(display, str) else "",
            )
        )
    return codings


def _resource_text(resource: JsonObject) -> str:
    values: list[str] = []
    for value in _walk(resource):
        if isinstance(value, str):
            values.append(value.casefold())
    return " ".join(values)


def _has_code(
    candidate: Candidate,
    resource_type: str,
    accepted_codes: set[str],
) -> bool:
    return any(
        code in accepted_codes
        for resource in candidate.resources.get(resource_type, [])
        for _, code, _ in _coding_tuples(resource)
    )


def _has_text(
    candidate: Candidate,
    resource_types: Iterable[str],
    terms: Iterable[str],
) -> bool:
    normalized_terms = tuple(term.casefold() for term in terms)
    return any(
        term in _resource_text(resource)
        for resource_type in resource_types
        for resource in candidate.resources.get(resource_type, [])
        for term in normalized_terms
    )


def _has_resources(candidate: Candidate, *resource_types: str) -> bool:
    return all(
        candidate.resources.get(resource_type) for resource_type in resource_types
    )


def _is_metabolic(candidate: Candidate) -> bool:
    return (
        _has_code(candidate, "Condition", TYPE_2_DIABETES_CODES)
        and _has_code(candidate, "Observation", GLUCOSE_OBSERVATION_CODES)
        and _has_text(
            candidate,
            ("MedicationRequest",),
            METABOLIC_MEDICATION_TERMS,
        )
    )


def _is_cardiovascular(candidate: Candidate) -> bool:
    return (
        _has_code(candidate, "Condition", HYPERTENSION_CODES)
        and _has_code(candidate, "Observation", BLOOD_PRESSURE_CODES)
        and _has_text(
            candidate,
            ("MedicationRequest",),
            CARDIOVASCULAR_MEDICATION_TERMS,
        )
    )


def _is_allergy_respiratory(candidate: Candidate) -> bool:
    respiratory = _has_code(
        candidate,
        "Condition",
        RESPIRATORY_CONDITION_CODES,
    ) or _has_text(
        candidate,
        ("Condition", "MedicationRequest", "Observation"),
        RESPIRATORY_TERMS,
    )
    return bool(candidate.resources.get("AllergyIntolerance")) and respiratory


def _is_sparse_control(candidate: Candidate) -> bool:
    optional_types = (
        "AllergyIntolerance",
        "Condition",
        "MedicationRequest",
        "Procedure",
        "DiagnosticReport",
    )
    missing_optional = any(
        not candidate.resources.get(resource_type) for resource_type in optional_types
    )
    return _has_resources(candidate, "Encounter", "Observation") and missing_optional


SCENARIOS = (
    Scenario(
        alias="metabolic-01",
        predicate=_is_metabolic,
        evidence_types=("Condition", "Observation", "MedicationRequest"),
    ),
    Scenario(
        alias="cardiovascular-01",
        predicate=_is_cardiovascular,
        evidence_types=("Condition", "Observation", "MedicationRequest"),
    ),
    Scenario(
        alias="allergy-respiratory-01",
        predicate=_is_allergy_respiratory,
        evidence_types=(
            "AllergyIntolerance",
            "Condition",
            "Observation",
            "MedicationRequest",
        ),
    ),
    Scenario(
        alias="sparse-control-01",
        predicate=_is_sparse_control,
        evidence_types=(
            "Encounter",
            "Observation",
            "AllergyIntolerance",
            "Condition",
            "MedicationRequest",
            "Procedure",
            "DiagnosticReport",
        ),
    ),
)


def _validate_safe_content(bundle: JsonObject, filename: str) -> None:
    for value in _walk(bundle):
        if isinstance(value, dict):
            resource_type = value.get("resourceType")
            if resource_type in FORBIDDEN_RESOURCE_TYPES:
                raise CohortError(
                    f"{filename}: forbidden resource type {resource_type}"
                )
            attachment_data = value.get("data")
            if isinstance(attachment_data, str) and len(attachment_data) > 128:
                raise CohortError(f"{filename}: embedded attachment data")
        elif isinstance(value, str):
            lowered = value.casefold()
            if any(marker in lowered for marker in SECRET_MARKERS):
                raise CohortError(f"{filename}: possible secret marker")


def load_candidate(
    path: Path,
    *,
    enforce_fixture_contract: bool = True,
) -> Candidate | None:
    """Load and validate one candidate, ignoring non-patient Bundle files."""

    bundle = _read_json(path)
    if bundle.get("resourceType") != "Bundle":
        return None
    if bundle.get("type") != "transaction":
        return None

    raw_entries = bundle.get("entry")
    if not isinstance(raw_entries, list):
        raise CohortError(f"{path.name}: transaction Bundle has no entry list")

    resources: dict[str, list[JsonObject]] = {}
    full_urls: set[str] = set()
    internal_references: set[str] = set()

    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise CohortError(f"{path.name}: entry {index} is not an object")
        full_url = raw_entry.get("fullUrl")
        resource = raw_entry.get("resource")
        request = raw_entry.get("request")
        if not isinstance(full_url, str) or not full_url:
            raise CohortError(f"{path.name}: entry {index} has no fullUrl")
        if full_url in full_urls:
            raise CohortError(f"{path.name}: duplicate fullUrl")
        if not isinstance(resource, dict):
            raise CohortError(f"{path.name}: entry {index} has no resource")
        if not isinstance(request, dict):
            raise CohortError(f"{path.name}: entry {index} has no request")
        method = request.get("method")
        url = request.get("url")
        if method not in {"POST", "PUT"} or not isinstance(url, str) or not url:
            raise CohortError(f"{path.name}: invalid transaction request")

        full_urls.add(full_url)
        typed_resource = cast(JsonObject, resource)
        resource_type = _resource_type(typed_resource)
        if not resource_type:
            raise CohortError(f"{path.name}: resource without resourceType")
        resources.setdefault(resource_type, []).append(typed_resource)

        for value in _walk(resource):
            if not isinstance(value, dict):
                continue
            reference = value.get("reference")
            if isinstance(reference, str) and reference.startswith("urn:uuid:"):
                internal_references.add(reference)

    unresolved = internal_references - full_urls
    if unresolved:
        raise CohortError(f"{path.name}: unresolved internal reference")

    patients = resources.get("Patient", [])
    if len(patients) != 1:
        return None
    patient_id = _resource_id(patients[0])
    if not patient_id:
        raise CohortError(f"{path.name}: Patient has no id")

    size_bytes = path.stat().st_size
    entry_count = len(raw_entries)
    if enforce_fixture_contract:
        if size_bytes > MAX_FIXTURE_BYTES:
            raise CohortError(f"{path.name}: exceeds fixture byte limit")
        if entry_count > MAX_FIXTURE_ENTRIES:
            raise CohortError(f"{path.name}: exceeds fixture entry limit")
        _validate_safe_content(bundle, path.name)
    return Candidate(
        path=path,
        bundle=bundle,
        patient_id=patient_id,
        resources=resources,
        size_bytes=size_bytes,
        entry_count=entry_count,
    )


def load_candidates(candidate_dir: Path) -> list[Candidate]:
    """Load every valid patient transaction Bundle in deterministic order."""

    if not candidate_dir.is_dir():
        raise CohortError("candidate FHIR directory does not exist")

    candidates: list[Candidate] = []
    errors: list[str] = []
    for path in sorted(candidate_dir.glob("*.json")):
        try:
            candidate = load_candidate(path, enforce_fixture_contract=False)
        except CohortError as error:
            errors.append(str(error))
            continue
        if candidate is not None:
            candidates.append(candidate)

    if errors:
        preview = "; ".join(errors[:5])
        raise CohortError(f"{len(errors)} candidate files failed validation: {preview}")
    if len(candidates) != EXPECTED_CANDIDATES:
        raise CohortError(
            f"expected {EXPECTED_CANDIDATES} patient candidates, "
            f"found {len(candidates)}"
        )
    return sorted(candidates, key=lambda candidate: candidate.patient_id)


def _is_relevant_evidence(
    scenario: Scenario,
    resource_type: str,
    resource: JsonObject,
) -> bool:
    codes = {code for _, code, _ in _coding_tuples(resource)}
    text = _resource_text(resource)
    if scenario.alias == "metabolic-01":
        if resource_type == "Condition":
            return bool(codes & TYPE_2_DIABETES_CODES)
        if resource_type == "Observation":
            return bool(codes & GLUCOSE_OBSERVATION_CODES)
        if resource_type == "MedicationRequest":
            return any(term in text for term in METABOLIC_MEDICATION_TERMS)
    if scenario.alias == "cardiovascular-01":
        if resource_type == "Condition":
            return bool(codes & HYPERTENSION_CODES)
        if resource_type == "Observation":
            return bool(codes & BLOOD_PRESSURE_CODES)
        if resource_type == "MedicationRequest":
            return any(term in text for term in CARDIOVASCULAR_MEDICATION_TERMS)
    if scenario.alias == "allergy-respiratory-01":
        if resource_type == "AllergyIntolerance":
            return True
        return bool(codes & RESPIRATORY_CONDITION_CODES) or any(
            term in text for term in RESPIRATORY_TERMS
        )
    return True


def _evidence(candidate: Candidate, scenario: Scenario) -> list[JsonObject]:
    evidence: list[JsonObject] = []
    for resource_type in scenario.evidence_types:
        resources = sorted(
            candidate.resources.get(resource_type, []),
            key=_resource_id,
        )
        relevant = [
            resource
            for resource in resources
            if _is_relevant_evidence(scenario, resource_type, resource)
        ]
        for resource in relevant[:5]:
            codes = sorted(
                {
                    f"{system}|{code}" if system else code
                    for system, code, _ in _coding_tuples(resource)
                }
            )
            item: JsonObject = {
                "resource_type": resource_type,
                "resource_id": _resource_id(resource),
            }
            if codes:
                item["codes"] = codes
            evidence.append(item)
    return evidence


def select_candidates(
    candidates: Sequence[Candidate],
) -> list[tuple[Scenario, Candidate]]:
    """Select the first unused patient-ID match for each scenario."""

    def eligible(candidate: Candidate) -> bool:
        if (
            candidate.size_bytes > MAX_FIXTURE_BYTES
            or candidate.entry_count > MAX_FIXTURE_ENTRIES
        ):
            return False
        try:
            _validate_safe_content(candidate.bundle, candidate.path.name)
        except CohortError:
            return False
        return True

    selected: list[tuple[Scenario, Candidate]] = []
    used_patient_ids: set[str] = set()
    for scenario in SCENARIOS:
        match = next(
            (
                candidate
                for candidate in candidates
                if candidate.patient_id not in used_patient_ids
                and eligible(candidate)
                and scenario.predicate(candidate)
            ),
            None,
        )
        if match is None:
            raise CohortError(f"no candidate matched scenario {scenario.alias}")
        selected.append((scenario, match))
        used_patient_ids.add(match.patient_id)
    return selected


def write_generation_metadata(args: argparse.Namespace) -> None:
    """Write non-patient generation provenance into the ignored output."""

    output = Path(args.output)
    config = Path(args.config)
    artifact = Path(args.artifact_path)
    if _sha256(artifact) != args.artifact_sha256:
        raise CohortError("Synthea artifact checksum mismatch")

    metadata: JsonObject = {
        "schema_version": 1,
        "synthetic_data": True,
        "generator": {
            "name": "Synthea",
            "version": args.synthea_version,
            "commit": args.synthea_commit,
            "license": "Apache-2.0",
            "artifact_sha256": args.artifact_sha256,
        },
        "runtime": {
            "java_version": args.java_version.strip(),
        },
        "generation": {
            "generated_at": args.generated_at,
            "patient_seed": 20260727,
            "clinician_seed": 104729,
            "reference_date": "2026-07-27",
            "population": 100,
            "overflow_population": False,
            "age_range": "45-80",
            "geography": "Massachusetts, United States",
            "config_path": "data/synthetic/synthea.properties",
            "config_sha256": _sha256(config),
        },
    }
    _write_json(output, metadata)


def build_manifest(
    generation_metadata: JsonObject,
    selected: Sequence[tuple[Scenario, Candidate]],
    fixture_dir: Path,
) -> JsonObject:
    """Copy exact selected Bundles and build their non-sensitive manifest."""

    if fixture_dir.exists() and any(fixture_dir.iterdir()):
        raise CohortError("fixture output directory must be empty")
    fixture_dir.mkdir(parents=True, exist_ok=True)

    fixtures: list[JsonObject] = []
    total_bytes = 0
    for scenario, candidate in selected:
        if candidate.size_bytes > MAX_FIXTURE_BYTES:
            raise CohortError(f"{scenario.alias}: exceeds fixture byte limit")
        if candidate.entry_count > MAX_FIXTURE_ENTRIES:
            raise CohortError(f"{scenario.alias}: exceeds fixture entry limit")
        _validate_safe_content(candidate.bundle, candidate.path.name)
        destination = fixture_dir / f"{scenario.alias}.json"
        shutil.copyfile(candidate.path, destination)
        size_bytes = destination.stat().st_size
        total_bytes += size_bytes
        fixtures.append(
            {
                "alias": scenario.alias,
                "patient_id": candidate.patient_id,
                "path": f"fhir/{destination.name}",
                "sha256": _sha256(destination),
                "size_bytes": size_bytes,
                "entry_count": candidate.entry_count,
                "missing_resource_types": sorted(
                    resource_type
                    for resource_type in scenario.evidence_types
                    if not candidate.resources.get(resource_type)
                ),
                "selection_evidence": _evidence(candidate, scenario),
            }
        )

    if total_bytes > MAX_COHORT_BYTES:
        raise CohortError("selected cohort exceeds total byte limit")

    return {
        "schema_version": 1,
        "synthetic_data": True,
        "generator": generation_metadata["generator"],
        "generation": generation_metadata["generation"],
        "candidate_count": len(cast(list[object], generation_metadata["candidates"])),
        "selected_count": len(fixtures),
        "fixtures": fixtures,
        "review": {
            "status": "reviewed",
            "reviewer": "codex-phase-1.2",
            "review_date": date.today().isoformat(),
            "checks": [
                "synthea_provenance",
                "fhir_r4_transaction_structure",
                "internal_references",
                "scenario_evidence",
                "forbidden_resources",
                "embedded_data",
                "secret_markers",
                "fixture_size",
            ],
        },
    }


def select_and_write(args: argparse.Namespace) -> None:
    """Select local cohort fixtures and enforce the committed checksum lock."""

    candidate_dir = Path(args.candidate_dir)
    fixture_dir = Path(args.fixture_dir)
    manifest_path = Path(args.manifest)
    metadata_path = Path(args.generation_metadata)
    lock_path = Path(args.lock)

    if manifest_path.exists():
        raise CohortError("cohort manifest already exists")
    lock = _read_json(lock_path)
    generation_metadata = _read_json(metadata_path)
    candidates = load_candidates(candidate_dir)
    generation_metadata["candidates"] = [
        {"patient_id": candidate.patient_id} for candidate in candidates
    ]
    selected = select_candidates(candidates)
    manifest = build_manifest(generation_metadata, selected, fixture_dir)
    _verify_manifest_lock(manifest, lock)
    _write_json(manifest_path, manifest)


def _verify_manifest_lock(manifest: JsonObject, lock: JsonObject) -> None:
    """Verify local selection metadata against the committed content lock."""

    raw_locked_fixtures = lock.get("fixtures")
    raw_manifest_fixtures = manifest.get("fixtures")
    if (
        lock.get("schema_version") != 1
        or lock.get("content") != "synthetic-cohort-checksums-only"
        or not isinstance(raw_locked_fixtures, list)
        or not isinstance(raw_manifest_fixtures, list)
    ):
        raise CohortError("invalid cohort lock")

    locked_by_alias: dict[str, JsonObject] = {}
    for raw_fixture in raw_locked_fixtures:
        if not isinstance(raw_fixture, dict):
            raise CohortError("invalid cohort lock fixture")
        fixture = cast(JsonObject, raw_fixture)
        alias = fixture.get("alias")
        if not isinstance(alias, str) or alias in locked_by_alias:
            raise CohortError("invalid cohort lock alias")
        locked_by_alias[alias] = fixture

    expected_aliases = {scenario.alias for scenario in SCENARIOS}
    if set(locked_by_alias) != expected_aliases:
        raise CohortError("cohort lock aliases do not match the contract")

    manifest_generator = manifest.get("generator")
    manifest_generation = manifest.get("generation")
    locked_generator = lock.get("generator")
    locked_generation = lock.get("generation")
    if not all(
        isinstance(value, dict)
        for value in (
            manifest_generator,
            manifest_generation,
            locked_generator,
            locked_generation,
        )
    ):
        raise CohortError("incomplete cohort lock provenance")

    for key in ("version", "commit", "artifact_sha256"):
        if cast(JsonObject, manifest_generator).get(key) != cast(
            JsonObject, locked_generator
        ).get(key):
            raise CohortError(f"cohort lock generator {key} mismatch")
    for key in (
        "patient_seed",
        "clinician_seed",
        "reference_date",
        "population",
        "overflow_population",
        "age_range",
        "geography",
        "config_sha256",
    ):
        if cast(JsonObject, manifest_generation).get(key) != cast(
            JsonObject, locked_generation
        ).get(key):
            raise CohortError(f"cohort lock generation {key} mismatch")

    if len(raw_manifest_fixtures) != len(locked_by_alias):
        raise CohortError("cohort lock fixture count mismatch")
    for raw_fixture in raw_manifest_fixtures:
        if not isinstance(raw_fixture, dict):
            raise CohortError("invalid manifest fixture entry")
        fixture = cast(JsonObject, raw_fixture)
        alias = fixture.get("alias")
        if not isinstance(alias, str) or alias not in locked_by_alias:
            raise CohortError("manifest alias is absent from cohort lock")
        locked_fixture = locked_by_alias[alias]
        for key in ("sha256", "size_bytes", "entry_count"):
            if fixture.get(key) != locked_fixture.get(key):
                raise CohortError(f"{alias}: cohort lock {key} mismatch")


def verify_local(args: argparse.Namespace) -> None:
    """Verify local fixtures against their manifest and committed lock."""

    manifest_path = Path(args.manifest)
    manifest = _read_json(manifest_path)
    lock = _read_json(Path(args.lock))
    _verify_manifest_lock(manifest, lock)
    raw_fixtures = manifest.get("fixtures")
    if manifest.get("synthetic_data") is not True or not isinstance(
        raw_fixtures,
        list,
    ):
        raise CohortError("invalid cohort manifest")
    if len(raw_fixtures) != len(SCENARIOS):
        raise CohortError("unexpected local fixture count")

    aliases: set[str] = set()
    scenarios = {scenario.alias: scenario for scenario in SCENARIOS}
    total_bytes = 0
    for raw_fixture in raw_fixtures:
        if not isinstance(raw_fixture, dict):
            raise CohortError("invalid manifest fixture entry")
        fixture = cast(JsonObject, raw_fixture)
        alias = fixture.get("alias")
        relative_path = fixture.get("path")
        checksum = fixture.get("sha256")
        if not all(
            isinstance(value, str) for value in (alias, relative_path, checksum)
        ):
            raise CohortError("incomplete manifest fixture entry")
        typed_alias = cast(str, alias)
        if typed_alias in aliases:
            raise CohortError("duplicate manifest alias")
        aliases.add(typed_alias)
        scenario = scenarios.get(typed_alias)
        if scenario is None:
            raise CohortError(f"unknown manifest alias: {typed_alias}")

        path = manifest_path.parent / cast(str, relative_path)
        candidate = load_candidate(path)
        if candidate is None:
            raise CohortError(f"{path.name}: not a patient transaction Bundle")
        if _sha256(path) != checksum:
            raise CohortError(f"{path.name}: checksum mismatch")
        if candidate.patient_id != fixture.get("patient_id"):
            raise CohortError(f"{path.name}: patient ID mismatch")
        if not scenario.predicate(candidate):
            raise CohortError(f"{path.name}: scenario evidence mismatch")
        if candidate.entry_count != fixture.get("entry_count"):
            raise CohortError(f"{path.name}: entry count mismatch")
        if candidate.size_bytes != fixture.get("size_bytes"):
            raise CohortError(f"{path.name}: byte size mismatch")
        total_bytes += candidate.size_bytes

    expected_aliases = {scenario.alias for scenario in SCENARIOS}
    if aliases != expected_aliases:
        raise CohortError("manifest aliases do not match the cohort contract")
    if total_bytes > MAX_COHORT_BYTES:
        raise CohortError("committed cohort exceeds total byte limit")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    metadata = commands.add_parser("write-generation-metadata")
    metadata.add_argument("--output", required=True)
    metadata.add_argument("--config", required=True)
    metadata.add_argument("--generated-at", required=True)
    metadata.add_argument("--java-version", required=True)
    metadata.add_argument("--artifact-path", required=True)
    metadata.add_argument("--artifact-sha256", required=True)
    metadata.add_argument("--synthea-version", required=True)
    metadata.add_argument("--synthea-commit", required=True)
    metadata.set_defaults(handler=write_generation_metadata)

    select = commands.add_parser("select")
    select.add_argument("--candidate-dir", required=True)
    select.add_argument("--generation-metadata", required=True)
    select.add_argument("--fixture-dir", required=True)
    select.add_argument("--manifest", required=True)
    select.add_argument("--lock", required=True)
    select.set_defaults(handler=select_and_write)

    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--lock", required=True)
    verify.set_defaults(handler=verify_local)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a cohort automation subcommand."""

    args = _parser().parse_args(argv)
    handler = cast(Callable[[argparse.Namespace], None], args.handler)
    try:
        handler(args)
    except CohortError as error:
        print(f"cohort error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
