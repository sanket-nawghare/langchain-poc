# Phase 1 — Synthetic Data and FHIR Integration Plan

This plan expands Phase 1 of the
[project roadmap](PROJECT_ROADMAP.md) into reviewable implementation
checkpoints and tracks implementation progress.

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
| 1.1 Cohort contract and provenance | Synthetic cohort purpose, size, scenarios, and provenance are explicit | `[x]` |
| 1.2 Generation and fixture review | Synthea output is reproducible, reviewed, checksum-locked, and local-only | `[x]` |
| 1.3 HAPI seed and reset workflow | Developers can import and verify the cohort with one command | `[x]` |
| 1.4 FHIR client foundation | Backend has a bounded async client with typed failures | `[x]` |
| 1.5 Retrieval and normalization | Required resources become minimum-necessary domain summaries | `[x]` |
| 1.6 Integration and Phase 1 gate | Seeded patient lookup and failure behavior are verified end to end | `[ ]` |

Every sub-phase follows the review protocol in `PHASE_0_FOUNDATIONS.md`: mark
in progress, implement only its scope, verify, update logs, mark complete, and
stop for review.

---

## Sub-phase 1.1 — Cohort Contract and Provenance

**Purpose:** Decide what synthetic data is needed before generating a large or
clinically unfocused dataset.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Define the small cohort size and representative clinical-QA scenarios.
- `[x]` Record Synthea version, configuration, seeds, reference date, generation
  metadata contract, and license/provenance.
- `[x]` Define stable demo aliases without depending on generated display names.
- `[x]` List required FHIR R4 resource types and intentionally excluded types.
- `[x]` Define fixture review criteria and size limits.
- `[x]` Confirm that no source data is real or organization-derived.

### Acceptance Criteria

- `[x]` Every planned patient alias supports a documented test or demo scenario.
- `[x]` Regeneration inputs are reproducible.
- `[x]` Data provenance and synthetic status are reviewable.

### Review Checkpoint

Review scenario usefulness, cohort size, resource scope, licensing, and
synthetic-only compliance before generation.

### Verification Record

Verified on 2026-07-27:

- Pinned the official Synthea `v4.0.0` release and full Git commit.
- Recorded Apache-2.0 provenance and exact FHIR R4 transaction exporter
  settings from the tagged upstream project.
- Defined a deterministic 100-patient candidate pool and four reviewed aliases:
  metabolic, cardiovascular, allergy/respiratory, and sparse control.
- Defined application resource scope, exclusions, deterministic selection,
  manifest fields, integrity checks, and hard fixture size limits.
- Confirmed `data/generated/` remains ignored and no patient data was generated,
  imported, or committed.
- `make check`, `make pre-commit`, and `git diff --check` passed.
- Aligned Git, Prettier, and ESLint ignores for the generated Vite cache found
  during verification.

---

## Sub-phase 1.2 — Generation and Fixture Review

**Purpose:** Generate the cohort reproducibly and retain only reviewed inputs
needed for deterministic development.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Pin or containerize the selected Synthea release.
- `[x]` Add a deterministic generation command using the recorded seed.
- `[x]` Write raw generated output only to ignored `data/generated/`.
- `[x]` Validate JSON and FHIR Bundle structure.
- `[x]` Review files for synthetic markers, accidental secrets, and scope.
- `[x]` Select the minimal reviewed cohort into ignored local storage.
- `[x]` Commit a metadata-only checksum lock without generated FHIR content.

### Acceptance Criteria

- `[x]` Repeating generation with the same inputs produces the expected cohort.
- `[x]` Unreviewed generated output remains ignored.
- `[x]` Local fixtures are small, valid, clearly synthetic, and documented.
- `[x]` No generated FHIR Bundle or detailed runtime manifest is tracked by Git.

### Review Checkpoint

Inspect every selected fixture, its provenance, and its checksum lock before it
is loaded.

### Verification Record

Verified on 2026-07-27:

- Pinned the official Synthea `v4.0.0` executable JAR by SHA-256 digest and
  verified it before every generation run.
- Generated exactly 100 candidates with the contracted seeds, reference date,
  age range, geography, history window, and FHIR R4 transaction settings.
- Confirmed all unreviewed candidates remain under ignored `data/generated/`.
- Deterministically selected four distinct scenario fixtures totaling about
  8.8 MiB; every fixture remains below 8 MiB and 1,000 Bundle entries.
- Confirmed every Bundle and the detailed runtime manifest are ignored; the
  committed lock contains only aliases, provenance, checksums, sizes, and entry
  counts.
- Verified valid UTF-8 JSON, transaction Bundle shape, one patient per Bundle,
  resolvable internal references, clinical scenario evidence, safe resource
  scope, forbidden payload absence, secret-marker absence, and SHA-256
  checksums.
- Repeated generation from an empty temporary directory and reproduced every
  selected patient ID, fixture checksum, entry count, and byte size exactly.
- Added focused unit coverage for selection, local-manifest and checksum-lock
  verification, checksum drift, and unresolved-reference rejection.
- No fixture had been imported into HAPI at the Phase 1.2 checkpoint.

---

## Sub-phase 1.3 — HAPI Seed and Reset Workflow

**Purpose:** Make synthetic FHIR loading safe, repeatable, and observable.

**Status:** `[x]` Complete — ready for review

### Reviewable Implementation Steps

1. **1.3.1 Target and reset safeguards** — restrict writes to the loopback HAPI
   endpoint, require explicit reset confirmation, and reset only HAPI's named
   PostgreSQL volume.
2. **1.3.2 Idempotent transaction seed** — verify the local checksum-locked
   cohort, reject unexpected server contents, and POST the four transaction
   Bundles through the FHIR API.
3. **1.3.3 Post-seed verification** — verify transaction responses, exact
   resource counts, stable patient IDs, repeat behavior, unavailable-server
   failure, and reset recovery.

Stop at this sub-phase's review checkpoint after all three steps pass.

### Deliverables

- `[x]` Import transaction bundles through the HAPI FHIR REST API.
- `[x]` Add `make fhir-seed` with idempotent or explicitly reset-first behavior.
- `[x]` Add a guarded FHIR reset command that cannot target an arbitrary server.
- `[x]` Verify imported resource counts and stable patient identifiers.
- `[x]` Fail clearly on unavailable HAPI, malformed bundles, or partial import.
- `[x]` Document pgAdmin as inspection-only for the HAPI-managed schema.

### Acceptance Criteria

- `[x]` A developer can seed the reviewed cohort with one command.
- `[x]` Re-running the documented workflow has predictable results.
- `[x]` Verification proves the expected synthetic patients are queryable.
- `[x]` No direct PostgreSQL inserts are used.

### Review Checkpoint

Review target safeguards, idempotency, error recovery, and verification output
before adding application retrieval.

### Verification Record

Verified on 2026-07-27:

- Restricted all seed, verify, and reset targets to explicit loopback HTTP
  endpoints with the exact `/fhir` path; unsafe schemes, hosts, credentials,
  paths, queries, fragments, and missing ports are rejected.
- Added two checksum-locked, ignored supporting batches for Synthea's
  conditional Organization and Practitioner references.
- Repeated clean Synthea generation and matched the checksum lock for all four
  patient Bundles and both supporting Bundles.
- Converted patient transaction POST requests in memory to stable-ID PUT
  requests without modifying locked resources.
- Seeded six Bundles through HAPI's FHIR API and verified 3,733 unique resources
  across 20 resource types plus four stable patient IDs.
- Re-ran the seed with `created=0` and `updated=3733`; counts and patient
  queries remained unchanged.
- Confirmed an unavailable loopback server fails clearly and unexpected HAPI
  data is refused before any cohort Bundle is posted.
- Confirmed the reset refuses without `CONFIRM=1`, validates the target and
  Compose volume label, replaces only `clinical-workflow-hapi-postgres`, retains
  Weaviate, verifies empty counts, and supports a clean reseed.
- Confirmed no direct PostgreSQL write is used; pgAdmin remains inspection-only.

---

## Sub-phase 1.4 — FHIR Client Foundation

**Purpose:** Isolate FHIR transport behavior behind an application-owned
interface.

**Status:** `[x]` Complete — ready for review

### Reviewable Implementation Steps

1. **1.4.1 Interface and failures** — define the application-owned read/search
   contract, supported resource types, search-page model, and safe typed errors.
2. **1.4.2 HAPI transport** — implement bounded timeouts/retries, FHIR JSON
   negotiation, strict resource and Bundle parsing, and base-URL confinement.
3. **1.4.3 Transport verification** — test success, pagination, not-found,
   timeout, unavailable, retry exhaustion, malformed response, and URL escape
   behavior without a live server.

Stop at this sub-phase's review checkpoint before normalization work begins.

### Deliverables

- `[x]` Define a read-only FHIR capability interface under `app/tools`.
- `[x]` Implement an async HAPI adapter under `app/services`.
- `[x]` Apply configured timeouts, bounded retries, and safe typed errors.
- `[x]` Support FHIR JSON content negotiation and Bundle parsing.
- `[x]` Prevent base-URL escape and unconstrained resource paths.
- `[x]` Add deterministic transport tests using an HTTP mock or stub server.
- `[x]` Ensure errors and logs exclude full resources and credentials.

### Acceptance Criteria

- `[x]` Client behavior does not leak HAPI or HTTP library objects into domain
  contracts.
- `[x]` Success, not-found, timeout, unavailable, and malformed-response paths
  are tested.
- `[x]` No write capability is exposed to workflow code.

### Review Checkpoint

Review interface size, retry safety, typed errors, URL construction, and log
redaction.

### Verification Record

Verified on 2026-07-27:

- Defined an application-owned async protocol for read, search, confined next
  page, and close operations across the eight approved Phase 1 resource types.
- Added application-owned FHIR resource/search-page types and distinct request,
  not-found, timeout, unavailable, and malformed-response errors.
- Added validated settings for a 5-second request timeout, at most two retries,
  and bounded exponential backoff.
- Implemented FHIR JSON negotiation, strict read and searchset parsing,
  stable-ID validation, a maximum page size of 100, and GET-only transport.
- Confined server-issued pagination links to the configured origin and FHIR
  base path; rejected external links, arbitrary resource types, unsafe base
  URLs, invalid IDs, and unsafe search values before transport.
- Verified bounded retries for timeouts and retryable HTTP status codes while
  excluding upstream response bodies and exception details from typed errors.
- Added deterministic mocked transport coverage for read, search, pagination,
  not-found, timeout, unavailable, malformed JSON, unexpected resources, and
  URL/request safeguards.
- Performed a read-only live smoke check against the seeded local HAPI server:
  one Patient read and an `_id` search returned the expected type and count
  without printing patient content.

---

## Sub-phase 1.5 — Retrieval and Normalization

**Purpose:** Convert relevant FHIR R4 resources into minimum-necessary,
provider-neutral patient context.

**Status:** `[x]` Complete — ready for review

### Reviewable Implementation Steps

1. **1.5.1 Summary contract** — define the minimum fields needed for the
   reviewed cohort, including explicit collection-truncation metadata.
2. **1.5.2 Bounded retrieval and normalization** — retrieve the approved
   resource types through the read-only client, follow confined pagination, and
   normalize variant and missing FHIR fields deterministically.
3. **1.5.3 Partial-record verification** — test all categories, pagination
   bounds, missing optional data, malformed fields, stable ordering, and
   exclusion of raw FHIR content.

Stop at this sub-phase's review checkpoint before API integration begins.

### Deliverables

- `[x]` Retrieve a patient by validated synthetic patient ID.
- `[x]` Retrieve conditions, allergies, medications, encounters, observations,
  procedures, and diagnostic/lab results required by the cohort scenarios.
- `[x]` Handle FHIR search pagination and Bundle links safely.
- `[x]` Normalize coding, display, status, effective time, and missing fields.
- `[x]` Extend domain contracts only where reviewed fixtures demonstrate need.
- `[x]` Bound returned collection sizes and exclude irrelevant raw fields.
- `[x]` Add fixture-driven normalization tests for partial and variant records.

### Acceptance Criteria

- `[x]` A known patient produces a stable normalized summary.
- `[x]` Missing optional resources produce empty or partial summaries safely.
- `[x]` Raw FHIR resources never enter workflow state or application logs.

### Review Checkpoint

Review clinical-field selection, missing-data semantics, pagination bounds, and
minimum-necessary output.

### Verification Record

Verified on 2026-07-27:

- Added a validated patient-summary service that uses only the application-owned
  read-only FHIR client and retrieves the seven approved clinical resource
  categories concurrently.
- Normalized code, display, status, effective time, compact observation values,
  patient display name variants, and safe fallback labels without exposing raw
  resources, resource IDs, references, addresses, notes, or narratives.
- Added configurable bounds of five pages and 100 records per resource type;
  repeated cursors fail safely and `truncated_categories` explicitly identifies
  incomplete bounded collections.
- Added deterministic ordering and 6 focused summary-service tests covering all
  categories, missing and variant fields, pagination, record and page bounds,
  repeated cursors, invalid IDs, missing patients, and raw-field exclusion.
- Preserved malformed-upstream-ID classification as a response error and added
  transport regression coverage.
- Ran a read-only smoke check against one seeded synthetic patient. All seven
  categories normalized successfully; observations and procedures reached the
  configured limit and were explicitly marked truncated. No patient content
  was printed.
- `make check` passed with 46 backend tests and 6 frontend tests, the frontend
  production build, and Compose validation.

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
