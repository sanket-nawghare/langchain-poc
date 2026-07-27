"""Synthetic cohort validation and selection tests."""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.synthetic_cohort import (
    CohortError,
    add_support_bundles,
    build_manifest,
    load_candidate,
    select_candidates,
    verify_local,
)


def coding_resource(
    resource_type: str,
    resource_id: str,
    code: str,
    display: str = "Synthetic display",
) -> dict[str, Any]:
    return {
        "resourceType": resource_type,
        "id": resource_id,
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": code,
                    "display": display,
                }
            ]
        },
    }


def write_bundle(
    path: Path,
    patient_id: str,
    resources: list[dict[str, Any]],
) -> None:
    entries = []
    for resource in [
        {"resourceType": "Patient", "id": patient_id},
        *resources,
    ]:
        resource_type = resource["resourceType"]
        resource_id = resource["id"]
        entries.append(
            {
                "fullUrl": f"urn:uuid:{resource_id}",
                "resource": resource,
                "request": {
                    "method": "PUT",
                    "url": f"{resource_type}/{resource_id}",
                },
            }
        )

    path.write_text(
        json.dumps(
            {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": entries,
            }
        ),
        encoding="utf-8",
    )


def required_candidates(tmp_path: Path) -> list[Path]:
    specifications = {
        "patient-a": [
            coding_resource("Condition", "condition-a", "44054006"),
            coding_resource("Observation", "observation-a", "4548-4"),
            coding_resource(
                "MedicationRequest",
                "medication-a",
                "860975",
                "Metformin 500 MG",
            ),
        ],
        "patient-b": [
            coding_resource("Condition", "condition-b", "38341003"),
            coding_resource("Observation", "observation-b", "85354-9"),
            coding_resource(
                "MedicationRequest",
                "medication-b",
                "197361",
                "Lisinopril 10 MG",
            ),
        ],
        "patient-c": [
            coding_resource("AllergyIntolerance", "allergy-c", "419199007"),
            coding_resource("Condition", "condition-c", "195967001"),
        ],
        "patient-d": [
            coding_resource("Encounter", "encounter-d", "185349003"),
            coding_resource("Observation", "observation-d", "29463-7"),
        ],
    }
    paths = []
    for patient_id, resources in specifications.items():
        path = tmp_path / f"{patient_id}.json"
        write_bundle(path, patient_id, resources)
        paths.append(path)
    return paths


def write_support_bundles(tmp_path: Path) -> None:
    specifications = {
        "hospitalInformation1.json": (
            ("Organization", "organization-1"),
            ("Location", "location-1"),
        ),
        "practitionerInformation1.json": (("Practitioner", "practitioner-1"),),
    }
    for filename, resources in specifications.items():
        entries = [
            {
                "resource": {
                    "resourceType": resource_type,
                    "id": resource_id,
                },
                "request": {
                    "method": "POST",
                    "url": resource_type,
                    "ifNoneExist": f"identifier=synthetic|{resource_id}",
                },
            }
            for resource_type, resource_id in resources
        ]
        (tmp_path / filename).write_text(
            json.dumps(
                {
                    "resourceType": "Bundle",
                    "type": "batch",
                    "entry": entries,
                }
            ),
            encoding="utf-8",
        )


def test_selects_one_distinct_patient_per_contract_scenario(
    tmp_path: Path,
) -> None:
    candidates = [
        candidate
        for path in required_candidates(tmp_path)
        if (candidate := load_candidate(path)) is not None
    ]

    selected = select_candidates(candidates)

    assert [scenario.alias for scenario, _ in selected] == [
        "metabolic-01",
        "cardiovascular-01",
        "allergy-respiratory-01",
        "sparse-control-01",
    ]
    assert len({candidate.patient_id for _, candidate in selected}) == 4


def test_manifest_and_committed_fixture_verification(
    tmp_path: Path,
) -> None:
    candidates = [
        candidate
        for path in required_candidates(tmp_path)
        if (candidate := load_candidate(path)) is not None
    ]
    selected = select_candidates(candidates)
    generation_metadata: dict[str, Any] = {
        "generator": {
            "name": "Synthea",
            "version": "v4.0.0",
            "commit": "test-commit",
            "license": "Apache-2.0",
            "artifact_sha256": "test-artifact-checksum",
        },
        "generation": {
            "patient_seed": 20260727,
            "clinician_seed": 104729,
            "reference_date": "2026-07-27",
            "population": 100,
            "overflow_population": False,
            "age_range": "45-80",
            "geography": "Massachusetts, United States",
            "config_sha256": "test-config-checksum",
        },
        "candidates": [{"patient_id": item.patient_id} for item in candidates],
    }
    fixture_dir = tmp_path / "fhir"
    manifest = build_manifest(generation_metadata, selected, fixture_dir)
    write_support_bundles(tmp_path)
    add_support_bundles(manifest, tmp_path, fixture_dir)
    manifest_path = tmp_path / "cohort-manifest.json"
    manifest_path.write_text(
        f"{json.dumps(manifest, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    lock: dict[str, Any] = {
        "schema_version": 1,
        "content": "synthetic-cohort-checksums-only",
        "generator": {
            key: generation_metadata["generator"][key]
            for key in ("version", "commit", "artifact_sha256")
        },
        "generation": {
            key: generation_metadata["generation"][key]
            for key in (
                "patient_seed",
                "clinician_seed",
                "reference_date",
                "population",
                "overflow_population",
                "age_range",
                "geography",
                "config_sha256",
            )
        },
        "fixtures": [
            {
                key: fixture[key]
                for key in ("alias", "sha256", "size_bytes", "entry_count")
            }
            for fixture in manifest["fixtures"]
        ],
        "support_bundles": [
            {
                key: support[key]
                for key in (
                    "alias",
                    "sha256",
                    "size_bytes",
                    "entry_count",
                    "resource_counts",
                )
            }
            for support in manifest["support_bundles"]
        ],
    }
    lock_path = tmp_path / "cohort-lock.json"
    lock_path.write_text(
        f"{json.dumps(lock, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )

    verify_local(
        argparse.Namespace(
            manifest=str(manifest_path),
            lock=str(lock_path),
        )
    )

    lock["fixtures"][0]["sha256"] = "unexpected"
    lock_path.write_text(
        f"{json.dumps(lock, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    with pytest.raises(CohortError, match="cohort lock sha256 mismatch"):
        verify_local(
            argparse.Namespace(
                manifest=str(manifest_path),
                lock=str(lock_path),
            )
        )


def test_rejects_unresolved_internal_reference(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    write_bundle(
        path,
        "patient-invalid",
        [
            {
                "resourceType": "Observation",
                "id": "observation-invalid",
                "subject": {"reference": "urn:uuid:missing-patient"},
            }
        ],
    )

    with pytest.raises(CohortError, match="unresolved internal reference"):
        load_candidate(path)
