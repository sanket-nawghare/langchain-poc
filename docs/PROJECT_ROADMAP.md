# AI Clinical Workflow Engine — Phased Project Roadmap

This document is the source of truth for delivery progress. It turns the
project concept in [`plan.md`](../plan.md) into incremental, testable phases.

> This project is an educational workflow demonstration, not a medical device.
> It must use synthetic patient data and must not present generated output as
> medical advice.

## How to Track Progress

Use these status markers throughout this document:

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked (add the reason beside the item)

When work begins or finishes:

1. Update the relevant checklist.
2. Add a dated entry to the progress log.
3. Record important technical decisions in the decision log.
4. Do not mark a phase complete until its exit criteria pass.

## Delivery Principles

- Build a thin end-to-end workflow before adding breadth.
- Keep clinical rules deterministic and testable; do not rely on the LLM alone
  for safety decisions.
- Require citations for guideline-backed answers.
- Keep patient data local and synthetic during development.
- Record workflow transitions, tool calls, approvals, and failures without
  leaking sensitive data.
- Make each provider and infrastructure dependency replaceable through a clear
  interface.

## Proposed Baseline Stack

The first implementation will use:

- Python, FastAPI, LangChain, and LangGraph
- React, Vite, Tailwind CSS, and React Flow
- SQLite for local application data, with a path to PostgreSQL
- HAPI FHIR in Docker
- Weaviate for guideline retrieval, using the existing local Docker image
- Synthea-generated FHIR data
- A provider-neutral LLM adapter configured through environment variables

This baseline can change through a recorded decision before implementation.

## Phase Summary

| Phase | Outcome | Status |
|---|---|---|
| 0. Foundations | Agreed scope, architecture, guardrails, and runnable skeleton | `[~]` |
| 1. FHIR Integration | Synthetic patients can be loaded and queried safely | `[ ]` |
| 2. Workflow MVP | One end-to-end LangGraph clinical-QA path works | `[ ]` |
| 3. Guidelines RAG | Responses retrieve and cite trusted guideline passages | `[ ]` |
| 4. Safety and Human Review | Risk rules can pause, approve, reject, and resume work | `[ ]` |
| 5. Product UI | Users can submit requests and inspect workflow progress | `[ ]` |
| 6. Quality and Observability | The system is measurable, auditable, and resilient | `[ ]` |
| 7. Packaging and Release | A new contributor can run and understand the project | `[ ]` |
| 8. Future Extensions | Optional capabilities are prioritized after the MVP | `[ ]` |

---

## Phase 0 — Foundations

**Goal:** Establish a safe, repeatable development base and lock the MVP scope.

Implementation is divided into stop-and-review checkpoints in the
[Phase 0 execution plan](PHASE_0_FOUNDATIONS.md).

### Scope

- `[x]` Define the first supported use case: clinical question answering for one
  synthetic patient.
- `[x]` Write explicit non-goals for the MVP, including diagnosis, prescribing,
  real patient data, and autonomous clinical decisions.
- `[x]` Create the initial repository structure for backend, frontend, workflow,
  tools, RAG, data, tests, and Docker assets.
- `[x]` Select the Python/package manager and Node/package manager.
- `[ ]` Add configuration loading and a documented `.env.example`.
- `[ ]` Add formatting, linting, type checking, unit test, and pre-commit setup.
- `[ ]` Add Docker Compose services for the backend dependencies.
- `[ ]` Define the core `WorkflowState` as a typed schema.
- `[ ]` Define error, API response, audit event, and citation schemas.
- `[ ]` Create architecture and data-flow diagrams.
- `[ ]` Add CI for backend and frontend quality checks.
- `[x]` Add a security/privacy policy for synthetic-only development.

### Exit Criteria

- `[ ]` A clean checkout can install dependencies and start the skeleton apps.
- `[x]` Backend health and readiness endpoints pass.
- `[x]` Frontend loads a placeholder screen.
- `[ ]` CI passes lint, type, and smoke-test checks.
- `[x]` MVP scope and safety boundaries are documented.

---

## Phase 1 — Synthetic Data and FHIR Integration

**Goal:** Provide reliable, read-only access to realistic synthetic patient
records through FHIR.

### Scope

- `[ ]` Run HAPI FHIR locally with persistent Docker storage.
- `[ ]` Add a repeatable Synthea generation/import workflow.
- `[ ]` Seed a small, versioned patient cohort for development and tests.
- `[ ]` Implement a FHIR client with timeouts, retries, and typed errors.
- `[ ]` Implement patient lookup by synthetic patient ID.
- `[ ]` Retrieve and normalize conditions, allergies, medications, encounters,
  observations, procedures, and lab results.
- `[ ]` Add pagination and FHIR bundle handling.
- `[ ]` Return a minimum-necessary patient summary to the workflow.
- `[ ]` Add fixtures or a stub FHIR server for deterministic tests.
- `[ ]` Verify logs do not contain full patient resources.

### Exit Criteria

- `[ ]` A developer can seed HAPI FHIR with one command.
- `[ ]` The API can return a normalized summary for a known synthetic patient.
- `[ ]` Missing patients, unavailable FHIR service, malformed resources, and
  partial records have tested behavior.
- `[ ]` No real patient data is required or included.

---

## Phase 2 — LangGraph Workflow MVP

**Goal:** Deliver one observable, end-to-end clinical-QA workflow before adding
more intent branches.

### Initial Graph

```text
Request
  -> validate input
  -> classify intent
  -> retrieve patient summary
  -> safety pre-check
  -> generate response
  -> audit
  -> return result
```

### Scope

- `[ ]` Implement the typed workflow state and reducers.
- `[ ]` Implement deterministic input validation.
- `[ ]` Implement structured intent classification with an `unknown` fallback.
- `[ ]` Implement the FHIR retrieval node using Phase 1 tools.
- `[ ]` Implement basic safety pre-check and response nodes.
- `[ ]` Add conditional graph routing and explicit terminal states.
- `[ ]` Expose a workflow-run endpoint in FastAPI.
- `[ ]` Assign correlation, workflow-run, and trace IDs.
- `[ ]` Persist workflow status and checkpoint state.
- `[ ]` Add timeout, retry, and graceful failure behavior per node.
- `[ ]` Test happy path, unsupported intent, invalid patient, and tool failure.

### Exit Criteria

- `[ ]` A clinical question for a seeded patient completes end to end.
- `[ ]` Each node emits inspectable state transitions and audit metadata.
- `[ ]` Structured-output parsing failures are handled safely.
- `[ ]` Replaying a test case produces deterministic routing.

---

## Phase 3 — Clinical Guidelines RAG

**Goal:** Ground clinical-QA responses in a curated guideline corpus with
traceable citations.

### Scope

- `[ ]` Define a source policy for allowed publishers and document licenses.
- `[ ]` Add a small, reviewed starter corpus from sources such as WHO, CDC,
  NICE, or ADA.
- `[ ]` Record document title, publisher, URL, publication date, version, page,
  and ingestion timestamp.
- `[ ]` Implement parsing, cleaning, chunking, embedding, and indexing.
- `[ ]` Make ingestion idempotent and support document replacement.
- `[ ]` Implement filtered retrieval and a minimum relevance threshold.
- `[ ]` Add the guideline retrieval tool and graph node.
- `[ ]` Require the response schema to include source citations.
- `[ ]` Refuse or qualify answers when evidence is missing or weak.
- `[ ]` Build a small retrieval evaluation dataset with expected sources.
- `[ ]` Measure recall, citation correctness, and unsupported-claim rate.

### Exit Criteria

- `[ ]` Seed questions retrieve expected guideline passages.
- `[ ]` Every guideline-backed statement exposes usable source metadata.
- `[ ]` Low-confidence retrieval triggers a safe fallback.
- `[ ]` Corpus ingestion and retrieval tests pass repeatably.

---

## Phase 4 — Safety and Human-in-the-Loop Review

**Goal:** Make high-risk or ambiguous cases pause for explicit review and resume
without losing state.

### Scope

- `[ ]` Define versioned, deterministic review rules and severity levels.
- `[ ]` Detect examples such as medication/allergy conflicts, urgent symptom
  language, missing critical context, and unsupported recommendations.
- `[ ]` Separate rule-based checks from LLM-assisted checks.
- `[ ]` Add a structured `SafetyResult` with reasons and evidence.
- `[ ]` Route flagged runs to a persisted `pending_review` state.
- `[ ]` Implement reviewer approve, reject, and request-changes actions.
- `[ ]` Resume the exact checkpoint after approval.
- `[ ]` Add reviewer identity, timestamp, rationale, and policy version to the
  audit trail.
- `[ ]` Prevent duplicate or stale approval actions.
- `[ ]` Test pause/resume behavior and authorization boundaries.

### Exit Criteria

- `[ ]` High-risk test cases never bypass review.
- `[ ]` Low-risk test cases proceed with recorded safety results.
- `[ ]` A pending run survives a backend restart.
- `[ ]` Every review action is attributable and auditable.

---

## Phase 5 — Product UI and Workflow Visualization

**Goal:** Provide a clear interface for submitting requests, reviewing evidence,
and understanding workflow execution.

### Scope

- `[ ]` Build patient selection and request submission views.
- `[ ]` Show loading, success, empty, blocked, and failure states.
- `[ ]` Render the generated response with patient-data and guideline citations.
- `[ ]` Visualize graph nodes and current execution state with React Flow.
- `[ ]` Add a review queue and approval/rejection interface.
- `[ ]` Show safety reasons before a reviewer acts.
- `[ ]` Add a run-history and audit-detail view.
- `[ ]` Add accessible keyboard navigation, labels, focus handling, and contrast.
- `[ ]` Avoid exposing unnecessary patient fields in the browser.
- `[ ]` Add component, integration, and critical end-to-end tests.

### Exit Criteria

- `[ ]` A user can complete the MVP workflow entirely through the UI.
- `[ ]` A reviewer can act on a pending run and see it resume.
- `[ ]` Workflow status is understandable without reading server logs.
- `[ ]` Critical UI journeys pass automated tests.

---

## Phase 6 — Quality, Security, and Observability

**Goal:** Make behavior measurable, failures diagnosable, and boundaries
defensible.

### Scope

- `[ ]` Add structured logs, metrics, traces, and correlation IDs.
- `[ ]` Add optional LangSmith tracing with documented opt-in data handling.
- `[ ]` Track latency, token usage, estimated cost, tool errors, retrieval
  quality, review rate, and completion rate.
- `[ ]` Create a golden workflow evaluation suite.
- `[ ]` Add prompt-injection and malicious-document tests.
- `[ ]` Add load, timeout, retry, and dependency-failure tests.
- `[ ]` Add dependency and secret scanning.
- `[ ]` Add API input limits, rate limits, and secure default headers.
- `[ ]` Document data retention, redaction, and deletion behavior.
- `[ ]` Add database migrations, backup notes, and recovery checks.
- `[ ]` Add a debugging/runbook document for common failures.

### Exit Criteria

- `[ ]` Golden evaluations meet recorded quality thresholds.
- `[ ]` Operators can trace one request across API, graph, tools, and storage.
- `[ ]` No known critical dependency or secret-scanning findings remain.
- `[ ]` Expected dependency failures degrade safely and are visible.

---

## Phase 7 — Packaging, Documentation, and First Release

**Goal:** Make the project reproducible, understandable, and ready for public
portfolio use.

### Scope

- `[ ]` Provide a one-command local startup path.
- `[ ]` Write setup, architecture, configuration, usage, and troubleshooting
  documentation.
- `[ ]` Document how to add a tool, graph node, model provider, and guideline.
- `[ ]` Add a guided demo scenario with seeded patient IDs and expected results.
- `[ ]` Add screenshots or a short demo recording.
- `[ ]` Add license, contribution guide, code of conduct, and security policy.
- `[ ]` Pin or constrain dependencies and publish release notes.
- `[ ]` Test the setup from a clean environment.
- `[ ]` Tag the first MVP release.

### Exit Criteria

- `[ ]` A new contributor can run the demo using only repository documentation.
- `[ ]` The demo proves FHIR retrieval, RAG citations, safety routing, human
  review, audit history, and workflow visualization.
- `[ ]` Limitations and the non-medical-device disclaimer are prominent.

---

## Phase 8 — Future Extensions

Begin only after the first release. Prioritize each item independently.

- `[ ]` Appointment-management intent and scheduling tool.
- `[ ]` Medication-information intent and expanded interaction checks.
- `[ ]` Additional clinical workflow templates.
- `[ ]` PostgreSQL production profile.
- `[ ]` Authentication and role-based access control.
- `[ ]` SMART on FHIR authorization.
- `[ ]` Multi-provider model routing and local Ollama profile.
- `[ ]` Streaming graph events and responses.
- `[ ]` Multilingual interface and evaluation.
- `[ ]` Deployment manifests for a hosted demo.

## Cross-Phase Definition of Done

A work item is complete only when:

- `[ ]` Implementation and relevant tests are committed together.
- `[ ]` Lint, types, unit tests, and applicable integration tests pass.
- `[ ]` Failure and empty states are covered.
- `[ ]` Logs and errors avoid unnecessary patient or secret data.
- `[ ]` Public interfaces and setup changes are documented.
- `[ ]` Important tradeoffs are recorded in the decision log.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucination or unsafe advice | Ground responses, use structured outputs, apply deterministic rules, and require human review |
| Stale or poorly licensed guidance | Curate sources, retain version metadata, and define a refresh/removal policy |
| Synthetic data mistaken for real data | Label fixtures clearly and prohibit real patient data in development |
| FHIR resource variability | Normalize at the tool boundary and test missing/partial fields |
| Prompt injection in documents or requests | Treat retrieved content as untrusted, constrain tools, and add adversarial evaluations |
| Vendor lock-in | Keep model, vector store, and tracing integrations behind interfaces |
| Scope growth | Finish the single clinical-QA vertical slice before adding intents |
| Non-reproducible local setup | Pin dependencies, seed fixed fixtures, and verify clean-environment setup |

## Decision Log

Add decisions as they are made. Link to a longer architecture decision record
when the explanation no longer fits here.

| Date | Decision | Rationale | Status |
|---|---|---|---|
| 2026-07-27 | Use FastAPI as the initial backend | Aligns with the Python LangChain/LangGraph ecosystem | Accepted |
| 2026-07-27 | Use Weaviate as the initial vector store | Reuses the existing local Docker image; the RAG layer will retain a replaceable vector-store interface | Accepted |
| 2026-07-27 | Build clinical QA before appointment and medication intents | Delivers a thin, testable vertical slice first | Accepted |
| 2026-07-27 | Use Python 3.12 with `uv` and Node.js 24 with pnpm | Provides reproducible dependency management and a conservative Python compatibility target | Accepted |
| 2026-07-27 | Keep workflow, tools, RAG, and adapters within one backend package | Makes dependency direction explicit while retaining provider-neutral interfaces | Accepted |

## Progress Log

Add the newest entry at the top.

| Date | Phase | Update | Next Step / Blocker |
|---|---|---|---|
| 2026-07-27 | Phase 0.2 | Fixed Makefile backend commands to bootstrap and use a pinned project-local `uv` | Re-run `make backend-sync`, then review before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Added a root Makefile for setup, development servers, tests, and frontend builds; completed the related Phase 0.5 task early | Review Makefile commands before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Completed and verified FastAPI and React/Vite application skeletons with locked dependencies and smoke tests | Stop for review before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Started backend and frontend application skeletons | Build and verify the minimal application shells |
| 2026-07-27 | Phase 0.1 | Completed MVP scope, foundation decisions, module boundaries, and development safety policy | Stop for review before sub-phase 0.2 |
| 2026-07-27 | Phase 0.1 | Started scope and technical-decision work on `create-foundations` | Document and review the MVP boundaries and foundation choices |
| 2026-07-27 | Phase 0 | Added the Phase 0 sub-phase plan for implementation on `create-foundations` | Review and begin sub-phase 0.1 |
| 2026-07-27 | Planning | Selected Weaviate instead of Qdrant for guideline retrieval | Confirm the local image version and Docker configuration during Phase 0 |
| 2026-07-27 | Planning | Converted the original concept into this phased delivery roadmap | Review Phase 0 scope and begin repository scaffolding |
