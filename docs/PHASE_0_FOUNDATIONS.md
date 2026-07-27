# Phase 0 — Foundations Execution Plan

This document expands Phase 0 of the
[project roadmap](PROJECT_ROADMAP.md) into small implementation checkpoints.
All Phase 0 changes will be made on the `create-foundations` branch.

## Objective

Create a safe, repeatable, and testable foundation for the first vertical
slice: clinical question answering for one synthetic patient.

Phase 0 establishes contracts and runnable application shells. It does not
implement FHIR retrieval, guideline ingestion, a production LangGraph
workflow, or clinical response generation.

## Tracking

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked

| Sub-phase | Deliverable | Status |
|---|---|---|
| 0.1 Scope and technical decisions | MVP boundaries and foundation choices are explicit | `[x]` |
| 0.2 Repository and application skeletons | Backend and frontend have an intentional structure | `[x]` |
| 0.3 Contracts and configuration | Typed shared concepts and safe configuration exist | `[x]` |
| 0.4 Local infrastructure | Required services have reproducible local configuration | `[x]` |
| 0.5 Quality automation | Local and CI quality gates are operational | `[x]` |
| 0.6 Documentation and foundation gate | Clean-checkout setup is verified and documented | `[~]` |

## Review Protocol

For each sub-phase:

1. Change its status to `[~]` before implementation.
2. Implement only the stated scope.
3. Run the listed verification checks and record any deviations.
4. Update the project progress and decision logs.
5. Change its status to `[x]` only when the acceptance criteria pass.
6. Stop for review before starting the next sub-phase.

Commit boundaries should normally match these sub-phases so each checkpoint is
easy to inspect or revert.

---

## Sub-phase 0.1 — Scope and Technical Decisions

**Purpose:** Resolve choices that affect the repository layout and prevent the
MVP from expanding while foundations are being built.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Define the MVP user story and one representative request/response
  example.
- `[x]` Document non-goals: diagnosis, prescribing, real patient data,
  autonomous medical decisions, appointment workflows, and medication workflows.
- `[x]` Confirm the backend and frontend technology choices.
- `[x]` Select supported Python and Node.js versions.
- `[x]` Select Python and Node.js dependency/package managers.
- `[x]` Decide the monorepo layout and module boundaries.
- `[x]` Confirm SQLite, HAPI FHIR, and Weaviate development roles.
- `[x]` Define the LLM provider abstraction boundary; no provider is required to
  run foundation health checks.
- `[x]` Record accepted decisions in the roadmap decision log or linked
  architecture decision records.
- `[x]` Add the synthetic-data-only and non-medical-device guardrails.

### Acceptance Criteria

- `[x]` A contributor can tell what Phase 0 and the MVP will and will not build.
- `[x]` Runtime and package-manager choices are unambiguous.
- `[x]` Every foundational technology choice has a short rationale.
- `[x]` No implementation-critical decision remains implicit.

### Review Checkpoint

Review scope, stack choices, directory boundaries, and guardrails before any
application scaffolding is generated.

---

## Sub-phase 0.2 — Repository and Application Skeletons

**Purpose:** Create minimal runnable shells without prematurely implementing
clinical behavior.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Create top-level backend, frontend, data, Docker, and test locations
  based on the accepted layout.
- `[x]` Initialize the Python backend package.
- `[x]` Add a FastAPI application with health and readiness endpoints.
- `[x]` Initialize the React/Vite/TypeScript frontend.
- `[x]` Add a minimal application shell and backend-health display.
- `[x]` Add shared repository files such as `.gitignore` and editor settings
  where useful.
- `[x]` Keep LangGraph, FHIR, RAG, and safety modules as explicit boundaries
  without implementing their Phase 1+ behavior.
- `[x]` Add focused smoke tests for both application shells.

### Acceptance Criteria

- `[x]` The backend starts locally and its health endpoint returns success.
- `[x]` The frontend starts locally and renders its placeholder screen.
- `[x]` Backend and frontend smoke tests pass.
- `[x]` No real patient data, secrets, or clinical logic is introduced.

### Review Checkpoint

Review repository ergonomics, dependency footprint, application startup, and
module ownership before defining durable contracts.

### Verification Record

Verified on 2026-07-27:

- Python 3.12.13 managed by `uv`; backend lockfile generated.
- Backend: `pytest` — 2 tests passed.
- Backend: Uvicorn started; `/health/live` and `/health/ready` returned HTTP 200.
- Frontend: `pnpm test` — 2 tests passed.
- Frontend: `pnpm build` — TypeScript and Vite production build passed.
- Frontend: Vite development server started and served the application HTML.

---

## Sub-phase 0.3 — Contracts and Configuration

**Purpose:** Establish typed boundaries early so later graph nodes and tools can
evolve without exchanging unstructured dictionaries.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Add environment-based backend configuration with startup validation.
- `[x]` Add frontend environment configuration for the API base URL.
- `[x]` Create a safe `.env.example` with documented variables and no secrets.
- `[x]` Define the initial typed `WorkflowState`.
- `[x]` Define API success/error envelopes.
- `[x]` Define audit-event, citation, safety-result, and workflow-status schemas.
- `[x]` Define identifier and timestamp conventions.
- `[x]` Add schema serialization and validation tests.
- `[x]` Ensure configuration errors fail clearly without printing secret values.

### Acceptance Criteria

- `[x]` The application starts with documented local defaults.
- `[x]` Invalid required configuration produces an actionable error.
- `[x]` Contracts serialize predictably and reject invalid data.
- `[x]` Phase 1 and Phase 2 can extend contracts without changing their basic
  ownership boundaries.

### Review Checkpoint

Review naming, optionality, serialization, and whether any schema encodes
premature clinical assumptions.

### Verification Record

Verified on 2026-07-27:

- `make check` passed.
- Backend: 10 tests passed, including settings, serialization, strict-field,
  timestamp, safety-consistency, API-error, CORS, and health tests.
- Frontend: 6 tests passed, including default, normalized, and invalid API URL
  configuration.
- TypeScript compilation and Vite production build passed.
- Python and frontend lockfiles remain reproducible.

---

## Sub-phase 0.4 — Local Infrastructure

**Purpose:** Make local dependencies reproducible while reusing the available
Weaviate image.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Inspect and record the available Weaviate image repository, tag, and
  version before writing service configuration.
- `[x]` Add Docker Compose configuration for Weaviate with health checks and a
  named persistent volume.
- `[x]` Add HAPI FHIR service configuration with health checks and persistent
  storage.
- `[x]` Document SQLite file location and volume behavior.
- `[x]` Configure ports and service URLs through environment variables.
- `[x]` Avoid enabling anonymous or externally exposed production-style access
  without documenting the local-only tradeoff.
- `[x]` Add backend readiness checks for configured dependencies without making
  the basic liveness endpoint depend on them.
- `[x]` Document service start, stop, health, and reset commands.

### Acceptance Criteria

- `[x]` Docker Compose configuration validates.
- `[x]` Weaviate and HAPI FHIR reach healthy states locally.
- `[x]` Backend readiness reports dependency availability accurately.
- `[x]` Data survives an ordinary service restart.
- `[x]` Resetting development data requires an explicit, documented action.

### Review Checkpoint

Review image versions, ports, persistence, health checks, resource use, and
local security assumptions before automating quality gates.

### Verification Record

Verified on 2026-07-27:

- `docker compose config --quiet` passed.
- Weaviate 1.36.0, HAPI FHIR 8.10.0, and PostgreSQL 16 reached healthy state.
- HAPI `/fhir/metadata` and Weaviate `/.well-known/ready` returned HTTP 200.
- Backend `/health/ready` returned HTTP 200 and reported SQLite, HAPI FHIR, and
  Weaviate available.
- Backend tests cover both ready and HTTP 503 failure behavior.
- All containers returned to healthy after an ordinary restart.
- HAPI's PostgreSQL schema remained present after restart with 58 public tables.
- `make check` passed: 13 backend tests, 6 frontend tests, frontend build, and
  Compose validation.

---

## Sub-phase 0.5 — Quality Automation

**Purpose:** Make the expected engineering standard executable locally and in
continuous integration.

**Status:** `[x]` Complete — ready for review

### Deliverables

- `[x]` Configure backend formatting, linting, static typing, and tests.
- `[x]` Configure frontend formatting, linting, type checking, and tests.
- `[x]` Add repository-level commands for common setup and verification tasks.
- `[x]` Add pre-commit checks that are fast enough for normal development.
- `[x]` Add CI jobs for backend and frontend checks.
- `[x]` Add a Docker Compose configuration validation check.
- `[x]` Enable dependency caching without caching secrets or generated patient
  data.
- `[x]` Document the required checks for every sub-phase.

### Acceptance Criteria

- `[x]` A single documented command runs all local quality checks.
- `[x]` Backend lint, types, and tests pass.
- `[x]` Frontend lint, types, and tests pass.
- `[x]` CI runs the same essential checks as local development.
- `[x]` A deliberately failing test or lint violation makes the relevant gate
  fail.

### Review Checkpoint

Review tool strictness, local runtime, CI parity, and whether checks produce
actionable failures.

### Verification Record

Verified on 2026-07-27:

- `make check` passed Ruff formatting and linting, strict mypy, 13 backend
  tests, Prettier, ESLint, TypeScript, 6 frontend tests, the Vite production
  build, and Docker Compose validation.
- `make pre-commit` passed all backend, frontend, and Compose hooks using the
  ignored project-local cache.
- A temporary unused Python import made `make backend-lint` fail with an
  actionable Ruff `F401` error. Removing it restored a passing gate.
- Frozen `uv` and pnpm installs passed after their lockfiles were updated.
- CI uses lockfile-keyed dependency caches and excludes environment files,
  databases, generated synthetic data, build output, and secrets.

---

## Sub-phase 0.6 — Documentation and Foundation Gate

**Purpose:** Prove that the foundation is reproducible and hand Phase 1 a clean,
documented starting point.

**Status:** `[~]` Awaiting the post-push CI run

### Deliverables

- `[x]` Add architecture, component-boundary, and local data-flow diagrams.
- `[x]` Document setup, configuration, startup, testing, and troubleshooting.
- `[x]` Document synthetic-data handling, logging/redaction expectations, and
  the non-medical-device disclaimer.
- `[x]` Document how future LangGraph nodes, tools, and provider adapters fit the
  structure.
- `[x]` Verify the complete setup from a clean checkout or equivalent clean
  environment.
- `[x]` Resolve or record all Phase 0 documentation and test gaps.
- `[x]` Update every Phase 0 checklist, decision, and progress entry.
- `[x]` Prepare the Phase 1 sub-phase plan without starting its implementation.

### Acceptance Criteria

- `[x]` A new contributor can install, configure, start, and test the skeleton
  using repository documentation.
- `[x]` Backend health and readiness behavior is documented and verified.
- `[x]` Frontend and backend smoke checks pass.
- `[ ]` CI is green.
- `[ ]` The parent roadmap's Phase 0 exit criteria all pass.

### Review Checkpoint

Perform a final Phase 0 review. Phase 1 begins only after this gate is accepted.

### Verification Record

Verified on 2026-07-27 from an isolated source-only copy containing no local
tooling, dependency directories, caches, environment files, application data,
build output, or Git history:

- `make setup` bootstrapped pinned `uv`, installed managed Python 3.12.13 and
  locked backend dependencies, and completed the frozen pnpm install.
- `make check` passed Ruff, strict mypy, 13 backend tests, Prettier, ESLint,
  TypeScript, 6 frontend tests, the Vite build, and Compose validation.
- After adding temporary Git metadata to model a real checkout,
  `make pre-commit` passed every configured hook.
- The isolated FastAPI server started on loopback port 18000;
  `/health/live` and dependency-aware `/health/ready` both returned HTTP 200.
- The isolated Vite server started on loopback port 15173 and served the
  application HTML.
- Startup verification exposed and resolved missing Makefile port overrides and
  incorrect frontend CLI argument forwarding.
- The actual GitHub `Quality` workflow remains pending until this Phase 0.6
  source state is committed and pushed.

## Phase 0 Completion Checklist

- `[ ]` All six sub-phases are complete.
- `[x]` All parent roadmap Phase 0 scope items are complete.
- `[ ]` All parent roadmap Phase 0 exit criteria pass.
- `[x]` The decision log reflects the implemented foundation.
- `[ ]` The progress log contains a final Phase 0 entry after CI confirmation.
- `[x]` No Phase 1+ feature was introduced without an explicit decision.
