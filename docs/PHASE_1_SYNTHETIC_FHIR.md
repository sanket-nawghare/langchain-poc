# Phase 1 — Synthetic Data and FHIR Integration Plan

This plan expands Phase 1 of the
[project roadmap](PROJECT_ROADMAP.md) into reviewable implementation
checkpoints. It is a planning artifact only; Phase 1 implementation has not
started.

## Objective

Provide repeatable, read-only access to a small, realistic synthetic patient
cohort through HAPI FHIR, while exposing only normalized minimum-necessary
patient context to later workflows.

## Prerequisite Already Delivered

Phase 0.4 provides pinned, persistent HAPI FHIR and PostgreSQL services,
loopback-only ports, health checks, lifecycle commands, and dependency-aware
backend readiness. Phase 1 will use this infrastructure without inserting
directly into PostgreSQL.

## Tracking

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked

| Sub-phase | Deliverable | Status |
|---|---|---|
| 1.1 Cohort contract and provenance | Synthetic cohort purpose, size, scenarios, and provenance are explicit | `[ ]` |
| 1.2 Generation and fixture review | Synthea output is reproducible, minimal, reviewed, and versioned intentionally | `[ ]` |
| 1.3 HAPI seed and reset workflow | Developers can import and verify the cohort with one command | `[ ]` |
| 1.4 FHIR client foundation | Backend has a bounded async client with typed failures | `[ ]` |
| 1.5 Retrieval and normalization | Required resources become minimum-necessary domain summaries | `[ ]` |
| 1.6 Integration and Phase 1 gate | Seeded patient lookup and failure behavior are verified end to end | `[ ]` |

Every sub-phase follows the review protocol in `PHASE_0_FOUNDATIONS.md`: mark
in progress, implement only its scope, verify, update logs, mark complete, and
stop for review.

---

## Sub-phase 1.1 — Cohort Contract and Provenance

**Purpose:** Decide what synthetic data is needed before generating a large or
clinically unfocused dataset.

### Deliverables

- `[ ]` Define the small cohort size and representative clinical-QA scenarios.
- `[ ]` Record Synthea version, configuration, seed, generation date, and
  license/provenance.
- `[ ]` Define stable demo aliases without depending on generated display names.
- `[ ]` List required FHIR R4 resource types and intentionally excluded types.
- `[ ]` Define fixture review criteria and size limits.
- `[ ]` Confirm that no source data is real or organization-derived.

### Acceptance Criteria

- `[ ]` Every patient exists to support a documented test or demo scenario.
- `[ ]` Regeneration inputs are reproducible.
- `[ ]` Data provenance and synthetic status are reviewable.

### Review Checkpoint

Review scenario usefulness, cohort size, resource scope, licensing, and
synthetic-only compliance before generation.

---

## Sub-phase 1.2 — Generation and Fixture Review

**Purpose:** Generate the cohort reproducibly and retain only reviewed inputs
needed for deterministic development.

### Deliverables

- `[ ]` Pin or containerize the selected Synthea release.
- `[ ]` Add a deterministic generation command using the recorded seed.
- `[ ]` Write raw generated output only to ignored `data/generated/`.
- `[ ]` Validate JSON and FHIR Bundle structure.
- `[ ]` Review files for synthetic markers, accidental secrets, and scope.
- `[ ]` Select and version the minimal reviewed cohort under
  `data/synthetic/`.
- `[ ]` Add fixture metadata and integrity checksums.

### Acceptance Criteria

- `[ ]` Repeating generation with the same inputs produces the expected cohort.
- `[ ]` Unreviewed generated output remains ignored.
- `[ ]` Versioned fixtures are small, valid, clearly synthetic, and documented.

### Review Checkpoint

Inspect every proposed fixture and its provenance before it is committed or
loaded.

---

## Sub-phase 1.3 — HAPI Seed and Reset Workflow

**Purpose:** Make synthetic FHIR loading safe, repeatable, and observable.

### Deliverables

- `[ ]` Import transaction bundles through the HAPI FHIR REST API.
- `[ ]` Add `make fhir-seed` with idempotent or explicitly reset-first behavior.
- `[ ]` Add a guarded FHIR reset command that cannot target an arbitrary server.
- `[ ]` Verify imported resource counts and stable patient identifiers.
- `[ ]` Fail clearly on unavailable HAPI, malformed bundles, or partial import.
- `[ ]` Document pgAdmin as inspection-only for the HAPI-managed schema.

### Acceptance Criteria

- `[ ]` A developer can seed the reviewed cohort with one command.
- `[ ]` Re-running the documented workflow has predictable results.
- `[ ]` Verification proves the expected synthetic patients are queryable.
- `[ ]` No direct PostgreSQL inserts are used.

### Review Checkpoint

Review target safeguards, idempotency, error recovery, and verification output
before adding application retrieval.

---

## Sub-phase 1.4 — FHIR Client Foundation

**Purpose:** Isolate FHIR transport behavior behind an application-owned
interface.

### Deliverables

- `[ ]` Define a read-only FHIR capability interface under `app/tools`.
- `[ ]` Implement an async HAPI adapter under `app/services`.
- `[ ]` Apply configured timeouts, bounded retries, and safe typed errors.
- `[ ]` Support FHIR JSON content negotiation and Bundle parsing.
- `[ ]` Prevent base-URL escape and unconstrained resource paths.
- `[ ]` Add deterministic transport tests using an HTTP mock or stub server.
- `[ ]` Ensure errors and logs exclude full resources and credentials.

### Acceptance Criteria

- `[ ]` Client behavior does not leak HAPI or HTTP library objects into domain
  contracts.
- `[ ]` Success, not-found, timeout, unavailable, and malformed-response paths
  are tested.
- `[ ]` No write capability is exposed to workflow code.

### Review Checkpoint

Review interface size, retry safety, typed errors, URL construction, and log
redaction.

---

## Sub-phase 1.5 — Retrieval and Normalization

**Purpose:** Convert relevant FHIR R4 resources into minimum-necessary,
provider-neutral patient context.

### Deliverables

- `[ ]` Retrieve a patient by validated synthetic patient ID.
- `[ ]` Retrieve conditions, allergies, medications, encounters, observations,
  procedures, and diagnostic/lab results required by the cohort scenarios.
- `[ ]` Handle FHIR search pagination and Bundle links safely.
- `[ ]` Normalize coding, display, status, effective time, and missing fields.
- `[ ]` Extend domain contracts only where reviewed fixtures demonstrate need.
- `[ ]` Bound returned collection sizes and exclude irrelevant raw fields.
- `[ ]` Add fixture-driven normalization tests for partial and variant records.

### Acceptance Criteria

- `[ ]` A known patient produces a stable normalized summary.
- `[ ]` Missing optional resources produce empty or partial summaries safely.
- `[ ]` Raw FHIR resources never enter workflow state or application logs.

### Review Checkpoint

Review clinical-field selection, missing-data semantics, pagination bounds, and
minimum-necessary output.

---

## Sub-phase 1.6 — Integration and Phase 1 Gate

**Purpose:** Prove that a clean developer environment can seed and read the
synthetic cohort safely.

### Deliverables

- `[ ]` Add an internal or development API path for normalized patient lookup,
  if needed for verification.
- `[ ]` Test the seed-to-query flow against local HAPI FHIR.
- `[ ]` Verify missing patient, unavailable service, malformed resource,
  pagination, and partial-record behavior.
- `[ ]` Run all repository quality gates.
- `[ ]` Verify setup from an isolated clean source copy.
- `[ ]` Update Phase 1 checklists, decisions, progress, and architecture docs.
- `[ ]` Prepare the Phase 2 sub-phase plan without implementing LangGraph.

### Acceptance Criteria

- `[ ]` `make fhir-seed` loads the expected reviewed cohort.
- `[ ]` The backend returns a normalized summary for a known synthetic patient.
- `[ ]` All required failure paths are deterministic and tested.
- `[ ]` Logs and errors contain no full patient resources.
- `[ ]` No real patient data is required or included.

### Review Checkpoint

Perform a final Phase 1 review. Phase 2 starts only after this gate is accepted.
