# Synthetic Patient Data

This directory must contain synthetic data only.

The [cohort contract](COHORT_CONTRACT.md) pins generator provenance,
reproducible inputs, four scenario-driven aliases, FHIR R4 resource scope, and
the review gate for Phase 1 fixtures.

Git contains no generated FHIR Bundle. The committed
[cohort checksum lock](cohort-lock.json) records only aliases, provenance,
sizes, entry counts, and SHA-256 checksums. It contains no patient IDs, names,
addresses, clinical codes, or resource content.

## Generation and Review Workflow

Requirements:

- Java 17 or newer.
- The repository-local `uv` bootstrap created by `make backend-sync`.
- Network access for the first run only, to download the pinned Synthea JAR.

Generate the ignored 100-patient candidate pool:

```bash
make synthea-generate
```

The command downloads Synthea `v4.0.0`, verifies the official JAR against the
pinned SHA-256 digest, applies `synthea.properties`, and writes only to the
Git-ignored `data/generated/synthea-v4.0.0/` directory. It refuses to reuse an
existing output directory.

Select and verify the four contract scenarios:

```bash
make synthea-select
make synthea-verify
```

Selection is deterministic by scenario order and FHIR `Patient.id`.
Verification checks transaction Bundle structure, internal references,
required scenario evidence, forbidden payload types, secret markers, size
limits, and the committed checksum lock. Both the selected `fhir/` directory
and its detailed runtime `cohort-manifest.json` are ignored by Git.

To regenerate deliberately, remove the existing outputs through the guarded
targets and then run the workflow again:

```bash
make synthea-fixtures-reset CONFIRM=1
make synthea-generated-reset CONFIRM=1
make synthea-cohort
```

Never force-add the ignored candidate pool, selected Bundles, or runtime
manifest.

## Local HAPI Seed Workflow

Start the infrastructure, then generate any missing local cohort files and
seed HAPI with one command:

```bash
make infra-up
make fhir-seed
```

The workflow verifies the checksum lock, imports the required Organization and
Practitioner support batches, converts generated patient transaction requests
to stable-ID PUTs, and verifies exact resource counts plus all four patient
IDs. Re-running `make fhir-seed` updates the same resources without creating
duplicates.

Useful lifecycle commands:

```bash
make fhir-verify
make fhir-reset CONFIRM=1
```

FHIR writes are restricted to an explicit loopback `http://.../fhir` target.
The reset refuses to run without confirmation, validates the HAPI target and
Docker volume label, and replaces only HAPI's PostgreSQL volume. It does not
remove Weaviate data.

## Reviewed Fixtures

| Alias | Purpose |
|---|---|
| `metabolic-01` | Diabetes condition, glucose observations, and related medication requests |
| `cardiovascular-01` | Hypertension condition, blood-pressure observations, and related medication requests |
| `allergy-respiratory-01` | Allergy plus respiratory clinical evidence |
| `sparse-control-01` | Valid record with deliberately absent optional categories |

The aliases above describe locally generated synthetic records for development
and testing. The records are not medical advice and must never be replaced
with real patient data.
