# Phase 2 — LangGraph Workflow MVP Plan

This plan expands Phase 2 of the
[project roadmap](PROJECT_ROADMAP.md) into reviewable implementation
checkpoints. It is a handoff plan only; no Phase 2 behavior is implemented
during the Phase 1 gate.

## Objective

Deliver one deterministic, observable clinical-question-answering path that
uses the Phase 1 normalized synthetic patient summary, applies an initial
safety check, returns a qualified response, and records minimum audit metadata.

## Prerequisites

- Phase 1 is accepted and the locked synthetic cohort can be seeded and queried
  through the normalized application API.
- Workflow state contains only provider-neutral domain contracts.
- No real patient data, autonomous diagnosis, prescribing, guideline RAG, or
  human-review implementation enters this phase.

## Tracking

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked

| Sub-phase | Deliverable | Status |
|---|---|---|
| 2.1 Execution contracts and graph skeleton | Graph dependencies, state transitions, reducers, and terminal outcomes are explicit | `[x]` |
| 2.2 Input validation and intent routing | Valid clinical-QA requests route deterministically and unsupported input fails safely | `[ ]` |
| 2.3 Patient retrieval and safety pre-check | The graph retrieves Phase 1 context and applies initial deterministic safety rules | `[ ]` |
| 2.4 Qualified response and audit | A provider-neutral model boundary returns structured output with disclaimers and minimal audit events | `[ ]` |
| 2.5 Run API, persistence, and recovery | Workflow runs have IDs, inspectable status, checkpoints, timeouts, and safe failures | `[ ]` |
| 2.6 Integration and Phase 2 gate | The complete thin path passes deterministic end-to-end and reproducibility checks | `[ ]` |

Every sub-phase must be marked in progress before implementation, split into
its own reviewable steps, verified independently, marked complete, and stopped
for review.

---

## Sub-phase 2.1 — Execution Contracts and Graph Skeleton

**Purpose:** Establish deterministic graph semantics before adding external
calls or model behavior.

**Status:** `[x]` Complete — ready for review

### Reviewable Implementation Steps

1. **2.1.1 State and transition semantics** — define the graph-state wrapper,
   append-only transition reducer, allowed status transitions, monotonic
   timestamps, terminal-state behavior, and safe failure codes.
2. **2.1.2 Runtime boundary and skeleton** — add the locked minimal LangGraph
   dependency, inject an application-owned clock through run-scoped context,
   and compile a graph containing only explicit start and safe
   not-yet-implemented terminal nodes.
3. **2.1.3 Determinism verification** — test reducer immutability, valid and
   invalid transitions, terminal behavior, topology, context injection, and
   byte-equivalent replay results.

The skeleton must terminate safely as `failed` with a stable
`workflow_not_implemented` code. It must not classify intent, retrieve patient
data, apply safety rules, call a model, persist state, or expose an API.

### Deliverables

- `[x]` Review and extend `WorkflowState` only for demonstrated graph needs.
- `[x]` Define application-owned protocols for workflow dependencies and clocks/ID
  generation needed by deterministic tests.
- `[x]` Define node input/output contracts, reducers, status transitions, failure
  codes, and explicit terminal states.
- `[x]` Add the minimal LangGraph dependency with a locked version.
- `[x]` Assemble a graph skeleton using no-op or fake dependencies.
- `[x]` Test state merging, invalid transitions, terminal behavior, and replay
  determinism.

### Acceptance Criteria

- `[x]` The graph compiles with only the two reviewed skeleton nodes.
- `[x]` Every run records `queued → running → failed` transitions and the stable
  `workflow_not_implemented` failure code.
- `[x]` Invalid, non-monotonic, and terminal-state transitions fail explicitly.
- `[x]` Replaying identical state with the same run-scoped clock produces an
  identical provider-neutral result.
- `[x]` External LangSmith tracing is forced off around graph execution even if
  a developer enables it globally.
- `[x]` The skeleton performs no clinical classification, retrieval, safety,
  generation, persistence, or API behavior.

### Review Checkpoint

Review state ownership, reducer behavior, dependency direction, and graph
topology before implementing classification.

### Verification Record

Verified on 2026-07-28:

- Added LangGraph `1.2.9` under the bounded `>=1.2.9,<1.3` dependency and
  explicitly locked the LangSmith runtime API used to disable external tracing;
  then regenerated the locked backend environment.
- Wrapped the durable `WorkflowState` in a small typed graph state with an
  immutable append reducer for validated `WorkflowTransition` records.
- Defined the allowed lifecycle matrix, terminal statuses, monotonic timestamp
  enforcement, and the invariant that only failed workflows carry a failure
  code. Final execution results additionally reject broken transition chains or
  histories that disagree with the final workflow state.
- Injected an application-owned clock through immutable run-scoped LangGraph
  context. IDs remain caller-owned because the skeleton does not create runs;
  run-ID generation is intentionally deferred to sub-phase 2.5.
- Compiled two native async nodes:
  `START → begin_execution → halt_unimplemented → END`. The terminal node
  always fails safely with `workflow_not_implemented`; no external capability
  is present.
- Wrapped graph invocation in `tracing_context(enabled=False)` so patient
  queries or future workflow state cannot be exported by inherited LangSmith
  environment settings. Reviewed redacted observability remains deferred.
- Added 15 focused cases covering reducer immutability, valid and invalid
  transitions, terminal states, timestamp and failure-code rules, exact graph
  topology, broken history rejection, runtime clock injection, tracing
  suppression, safe output, and deterministic replay.
- `make check` passed with 68 backend tests and 6 frontend tests, the frontend
  production build, and Compose validation.

---

## Sub-phase 2.2 — Input Validation and Intent Routing

**Purpose:** Ensure only bounded supported requests enter the clinical path.

### Planned Deliverables

- Define the workflow-run request contract and query bounds.
- Implement deterministic patient-ID and query validation.
- Add a structured intent-classifier interface with a deterministic fake.
- Support `clinical_qa` and an explicit `unknown` fallback only.
- Route invalid and unsupported requests to safe terminal results.
- Test valid, empty, oversized, ambiguous, unsupported, and malformed
  classifier output.

### Review Checkpoint

Review accepted input, fallback behavior, and structured-output parsing before
patient retrieval is connected.

---

## Sub-phase 2.3 — Patient Retrieval and Safety Pre-check

**Purpose:** Bring Phase 1 context into the graph without exposing raw FHIR
data, then apply an initial deterministic risk screen.

### Planned Deliverables

- Add a FHIR retrieval node using the Phase 1 summary capability.
- Map missing, unavailable, timeout, malformed, and partial/truncated context
  to explicit workflow results.
- Define the initial versioned safety policy and rule result contract.
- Add bounded rules for urgent-language and missing-critical-context examples.
- Keep Phase 4 human approval/resume behavior out of scope.
- Test successful, sparse, truncated, missing-patient, dependency-failure, and
  safety-flag routes.

### Review Checkpoint

Review minimum patient context, failure semantics, safety-rule determinism, and
the boundary with future human review.

---

## Sub-phase 2.4 — Qualified Response and Audit

**Purpose:** Generate a structured educational response while preserving
provider neutrality and minimal audit data.

### Planned Deliverables

- Define a provider-neutral structured model capability and deterministic fake.
- Generate a bounded answer with the required synthetic/educational disclaimer.
- Make the absence of Phase 3 guideline evidence explicit; do not fabricate
  citations.
- Validate model output and fail safely on malformed or unsupported content.
- Emit minimal audit events for node transitions, tool calls, results, and
  failures without queries, patient context, prompts, or model payloads.
- Test success, malformed output, timeout, safety stop, disclaimer, empty
  citations, and audit redaction.

### Review Checkpoint

Review response qualification, model isolation, failure fallback, and audit
field selection before persistence or HTTP integration.

---

## Sub-phase 2.5 — Run API, Persistence, and Recovery

**Purpose:** Make workflow execution identifiable, inspectable, durable, and
safe across dependency failures.

### Planned Deliverables

- Add workflow-run and status API contracts and routes.
- Assign request, correlation, workflow-run, and trace identifiers.
- Persist workflow metadata and checkpoints in application-owned SQLite.
- Add per-node timeout, bounded retry, and graceful failure policies.
- Support safe status inspection and deterministic replay of test cases.
- Test concurrent IDs, persistence, restart recovery, timeout, retry
  exhaustion, and error-envelope redaction.

### Review Checkpoint

Review API shape, storage schema, checkpoint boundaries, retry safety, and
recovery behavior before the end-to-end gate.

---

## Sub-phase 2.6 — Integration and Phase 2 Gate

**Purpose:** Prove the thin clinical-QA graph works from API request through
normalized patient context, safety, response, audit, and persistence.

### Planned Deliverables

- Test the full seeded-patient happy path using deterministic fake model
  dependencies.
- Test unsupported intent, invalid and missing patient, tool failure, malformed
  model output, safety flag, timeout, and replay behavior.
- Verify inspectable state transitions, correlation metadata, and audit
  redaction.
- Run repository and isolated-source quality gates.
- Update architecture, development, contracts, decisions, and roadmap status.
- Prepare the Phase 3 sub-phase plan without implementing guideline RAG.

### Phase Exit Criteria

- A clinical question for a seeded synthetic patient completes end to end.
- Every node exposes deterministic, testable state transitions.
- Unsupported input and dependency/model failures terminate safely.
- Replaying a deterministic test produces the same routing and result.
- No real patient data, raw FHIR resource, prompt body, or model payload is
  persisted or logged.

### Review Checkpoint

Perform the final Phase 2 review. Phase 3 begins only after this gate is
accepted.
