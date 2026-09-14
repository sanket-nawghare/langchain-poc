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
| 0. Foundations | Agreed scope, architecture, guardrails, and runnable skeleton | `[x]` |
| 1. FHIR Integration | Synthetic patients can be loaded and queried safely | `[x]` |
| 2. Workflow MVP | One end-to-end LangGraph clinical-QA path works | `[x]` |
| 3. Guidelines RAG | Responses retrieve and cite trusted guideline passages | `[x]` |
| 4. Grounded Generation, Safety, and Human Review | A real grounded model plus risk rules can safely draft, pause, review, and resume work | `[x]` |
| 5. Product UI | Users can submit requests and inspect workflow progress | `[~]` |
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
- `[x]` Add configuration loading and a documented `.env.example`.
- `[x]` Add formatting, linting, type checking, unit test, and pre-commit setup.
- `[x]` Add Docker Compose services for the backend dependencies.
- `[x]` Define the core `WorkflowState` as a typed schema.
- `[x]` Define error, API response, audit event, and citation schemas.
- `[x]` Create architecture and data-flow diagrams.
- `[x]` Add CI for backend and frontend quality checks.
- `[x]` Add a security/privacy policy for synthetic-only development.

### Exit Criteria

- `[x]` A clean checkout can install dependencies and start the skeleton apps.
- `[x]` Backend health and readiness endpoints pass.
- `[x]` Frontend loads a placeholder screen.
- `[x]` CI passes lint, type, and smoke-test checks.
- `[x]` MVP scope and safety boundaries are documented.

---

## Phase 1 — Synthetic Data and FHIR Integration

**Goal:** Provide reliable, read-only access to realistic synthetic patient
records through FHIR.

### Scope

- `[x]` Run HAPI FHIR locally with persistent Docker storage. Completed early
  in Phase 0.4.
- `[x]` Add a repeatable Synthea generation/import workflow.
- `[x]` Seed a small, reproducibly locked local patient cohort for development
  and tests.
- `[x]` Implement a FHIR client with timeouts, retries, and typed errors.
- `[x]` Implement patient lookup by synthetic patient ID.
- `[x]` Retrieve and normalize conditions, allergies, medications, encounters,
  observations, procedures, and lab results.
- `[x]` Add pagination and FHIR bundle handling.
- `[x]` Return a minimum-necessary patient summary to the workflow.
- `[x]` Add fixtures or a stub FHIR server for deterministic tests.
- `[x]` Verify logs do not contain full patient resources.

### Exit Criteria

- `[x]` A developer can seed HAPI FHIR with one command.
- `[x]` The API can return a normalized summary for a known synthetic patient.
- `[x]` Missing patients, unavailable FHIR service, malformed resources, and
  partial records have tested behavior.
- `[x]` No real patient data is required or included.

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

- `[x]` Implement the typed workflow state and reducers.
- `[x]` Implement deterministic input validation.
- `[x]` Implement structured intent classification with an `unknown` fallback.
- `[x]` Implement the FHIR retrieval node using Phase 1 tools.
- `[x]` Implement the basic safety pre-check.
- `[x]` Implement response nodes.
- `[x]` Add conditional graph routing and explicit terminal states.
- `[x]` Expose a workflow-run endpoint in FastAPI.
- `[x]` Assign correlation, workflow-run, and trace IDs.
- `[x]` Persist workflow status and checkpoint state.
- `[x]` Add timeout, retry, and graceful failure behavior per node.
- `[x]` Test happy path, unsupported intent, invalid patient, and tool failure.

### Exit Criteria

- `[x]` A clinical question for a seeded patient completes end to end.
- `[x]` Each node emits inspectable state transitions or audit metadata.
- `[x]` Structured-output parsing failures are handled safely.
- `[x]` Replaying a test case produces deterministic routing.

---

## Phase 3 — Clinical Guidelines RAG

**Goal:** Ground clinical-QA responses in a curated guideline corpus with
traceable citations.

Implementation will proceed through the review checkpoints in the
[Phase 3 execution plan](PHASE_3_GUIDELINES_RAG.md).

### Scope

- `[x]` Define a source policy for allowed publishers and document licenses.
- `[x]` Add a small, reviewed starter corpus from sources such as WHO, CDC,
  NICE, or ADA.
- `[x]` Record document title, publisher, URL, publication date, version, page,
  and ingestion timestamp.
- `[x]` Implement parsing, cleaning, chunking, embedding, and indexing.
- `[x]` Make ingestion idempotent and support document replacement.
- `[x]` Implement filtered retrieval and a minimum relevance threshold.
- `[x]` Add the guideline retrieval tool and graph node.
- `[x]` Require the response schema to include source citations.
- `[x]` Refuse or qualify answers when evidence is missing or weak.
- `[x]` Build a small retrieval evaluation dataset with expected sources.
- `[x]` Measure retrieval expectations, citation correctness, safe qualification,
  and unsupported-claim prevention through deterministic gates.

### Exit Criteria

- `[x]` Seed questions retrieve expected guideline passages.
- `[x]` Every guideline-backed response exposes usable source metadata.
- `[x]` Low-confidence retrieval triggers a safe review fallback.
- `[x]` Corpus ingestion and retrieval tests pass repeatably.

---

## Phase 4 — Safety and Human-in-the-Loop Review

**Goal:** Generate grounded drafts through a configured LLM, then make high-risk
or ambiguous cases pause for explicit review and resume without losing state.

Implementation proceeds through the review checkpoints in the
[Phase 4 execution plan](PHASE_4_SAFETY_AND_HUMAN_REVIEW.md).

### Scope

- `[x]` Add provider-backed grounded response generation using bounded patient
  context and retrieved guideline excerpts.
- `[x]` Keep structured answer parsing, citations, disclaimers, and routing
  application-owned.
- `[x]` Add provider timeout, retry, authentication, rate-limit, unavailable,
  malformed-output, and context-limit failure handling.
- `[x]` Add an opt-in real-provider live gate while keeping tests and startup
  credential-free.
- `[x]` Define versioned, deterministic review rules and severity levels.
- `[x]` Detect examples such as medication/allergy conflicts, urgent symptom
  language, missing critical context, and unsupported recommendations.
- `[x]` Separate rule-based checks from LLM-assisted checks.
- `[x]` Add a structured `SafetyResult` with reasons and evidence.
- `[x]` Route flagged runs to a persisted `pending_review` state.
- `[x]` Implement reviewer approve, reject, and request-changes actions.
- `[x]` Resume the exact checkpoint after approval.
- `[x]` Add reviewer identity, timestamp, rationale, and policy version to the
  audit trail.
- `[x]` Prevent duplicate or stale approval actions.
- `[x]` Test pause/resume behavior and authorization boundaries.

### Exit Criteria

- `[x]` A configured real LLM produces a strictly parsed, grounded answer draft.
- `[x]` No provider can fabricate or replace citations or the disclaimer.
- `[x]` High-risk test cases never bypass review.
- `[x]` Low-risk test cases proceed with recorded safety results.
- `[x]` A pending run survives a backend restart.
- `[x]` Every review action is attributable and auditable.

---

## Phase 5 — Product UI and Workflow Visualization

**Goal:** Provide a clear interface for submitting requests, reviewing evidence,
and understanding workflow execution.

Implementation will proceed through the review checkpoints in the
[Phase 5 execution plan](PHASE_5_PRODUCT_UI.md).

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
| 2026-08-03 | Give LangGraph sole ownership of the configured LLM retry budget and deterministically bound normalized fields when projecting grounded context | Prevents multiplicative SDK/workflow retries and ensures valid normalized synthetic records cannot fail before provider invocation merely because the provider boundary is intentionally smaller | Accepted |
| 2026-08-03 | Build a bounded grounded request only after retrieval and deterministic safety pass, then keep citations and qualifications application-owned | Prevents identifiers, raw FHIR data, full documents, provider objects, model-created citation identity, and unreviewed model output from controlling the durable workflow result | Accepted |
| 2026-08-03 | Use OpenAI Responses with `gpt-5.6-sol` as the first real grounded-generation provider while retaining strict provider-neutral request, response, and failure contracts | Current official guidance identifies the model as the flagship and supports Responses structured outputs; keeping tools, citations, disclaimers, safety, and routing application-owned prevents the provider from controlling durable clinical behavior | Accepted |
| 2026-08-03 | Use pinned strict pypdf parsing with page-confined 2,400-character chunks and a content-free deterministic chunk lock | Preserves exact page/source lineage, keeps outputs bounded and reproducible, and detects parser or source drift before vector indexing | Accepted |
| 2026-08-03 | Use two checksum-locked WHO PDFs as a local-index-only starter corpus and commit metadata rather than document content | Directly supports the seeded diabetes and hypertension scenarios while preserving exact provenance and a conservative repository-redistribution boundary | Accepted |
| 2026-08-03 | Separate authoritative-publisher eligibility from per-document permission and allow only current, explicitly indexable guideline versions into retrieval | Publisher reputation does not grant redistribution or indexing rights; exact provenance, license review, lifecycle, and checksum records make corpus decisions reviewable | Accepted |
| 2026-07-28 | Raise the default normalized FHIR record cap from 100 to 500 while retaining 100-resource pages and a five-page maximum | All four checksum-locked Synthea fixtures exceed 100 observations; verified maxima of 354 observations and 139 procedures fit within the existing reviewed hard cap and allow a real seeded Phase 2 happy path without hiding truncation | Accepted |
| 2026-07-28 | Persist redacted queued/final workflow snapshots in application-owned SQLite and fail interrupted work on startup | Provides inspectable recovery without storing query/patient context or automatically replaying clinical work | Accepted |
| 2026-07-28 | Let response generators draft bounded answer text only; application code owns disclaimers and citations | Prevents a model/provider from removing educational qualifications or fabricating evidence | Accepted |
| 2026-07-27 | Use FastAPI as the initial backend | Aligns with the Python LangChain/LangGraph ecosystem | Accepted |
| 2026-07-27 | Use Weaviate as the initial vector store | Reuses the existing local Docker image; the RAG layer will retain a replaceable vector-store interface | Accepted |
| 2026-07-27 | Build clinical QA before appointment and medication intents | Delivers a thin, testable vertical slice first | Accepted |
| 2026-07-27 | Use Python 3.12 with `uv` and Node.js 24 with pnpm | Provides reproducible dependency management and a conservative Python compatibility target | Accepted |
| 2026-07-27 | Keep workflow, tools, RAG, and adapters within one backend package | Makes dependency direction explicit while retaining provider-neutral interfaces | Accepted |
| 2026-07-27 | Back HAPI FHIR with PostgreSQL 16 | PostgreSQL is already available locally, is supported by HAPI, and provides explicit durable storage | Accepted |
| 2026-07-27 | Bind development services to loopback and keep Weaviate anonymous access local-only | Supports simple local development without presenting the configuration as production-safe | Accepted |
| 2026-07-27 | Mirror locked local quality gates in separate backend, frontend, and Compose CI jobs | Keeps failures focused while preserving local/CI parity and safe dependency caching | Accepted |
| 2026-07-27 | Keep external FHIR, retrieval, and model payloads inside adapters | Prevents vendor-specific objects and excessive patient context from entering durable workflow state | Accepted |
| 2026-07-27 | Pin Synthea v4.0.0 and select four scenario-driven fixtures from deterministic candidate generation | Makes cohort provenance and selection reproducible | Accepted |
| 2026-07-27 | Pin the official Synthea v4.0.0 executable JAR by SHA-256 and cap reviewed fixtures at 8 MiB and 1,000 entries each | Makes execution provenance verifiable while accommodating the smallest deterministic metabolic scenario | Accepted |
| 2026-07-27 | Keep generated FHIR Bundles and the detailed runtime manifest out of Git; commit only a non-clinical checksum lock | Avoids repository bloat and generated clinical content while preserving exact reproducibility | Accepted |
| 2026-07-27 | Convert generated patient POST requests to stable-ID PUTs only at seed time and load checksum-locked provider support batches first | Makes HAPI seeding idempotent while preserving the reviewed generated resources and satisfying conditional references | Accepted |
| 2026-07-27 | Reset FHIR by replacing only the validated local HAPI PostgreSQL Compose volume | Provides predictable recovery without enabling destructive HAPI operations or deleting Weaviate data | Accepted |
| 2026-07-27 | Expose only eight read-only resource types through an application-owned async FHIR protocol | Prevents write operations and HTTP/HAPI objects from crossing into workflow-facing code | Accepted |
| 2026-07-27 | Bound FHIR reads to a 5-second timeout, two retries, 100-resource pages, and same-origin/base-path pagination | Keeps dependency failures and server-issued links constrained and testable | Accepted |
| 2026-07-27 | Normalize at most 100 records per type across at most five pages and expose truncated categories explicitly | Keeps workflow context bounded without silently presenting partial clinical collections as complete | Accepted |
| 2026-07-27 | Expose normalized synthetic patient lookup as a loopback-development GET route with stable safe error envelopes | Verifies the complete application boundary without exposing raw FHIR resources, upstream payloads, or write capabilities | Accepted |
| 2026-07-28 | Use LangGraph 1.2.x with typed shared state, append-only transition reduction, and immutable run-scoped dependency context | Keeps orchestration explicit, replayable, provider-neutral, and independently testable | Accepted |
| 2026-07-28 | Make the Phase 2.1 skeleton terminate as failed with `workflow_not_implemented` | Prevents incomplete orchestration from appearing clinically successful before later nodes are reviewed | Accepted |
| 2026-07-28 | Force external LangSmith tracing off around graph invocation | Prevents inherited developer environment settings from exporting patient queries or complete workflow state before redacted observability is designed | Accepted |
| 2026-07-28 | Bound workflow queries to 2,000 characters and align patient IDs with FHIR's 64-character safe-ID grammar | Rejects oversized or unsafe input before orchestration and keeps application and FHIR identifier boundaries consistent | Accepted |
| 2026-07-28 | Use a conservative deterministic intent classifier until a reviewed provider-backed classifier is needed | Makes Phase 2 routing replayable and sends unsupported, mixed, or ambiguous requests to the safe `unknown` fallback | Accepted |

## Progress Log

Add the newest entry at the top.

| Date | Phase | Update | Next Step / Blocker |
|---|---|---|---|
| 2026-09-14 | Phase 5.4 | Added read-only React Flow workflow visualization, completed/current-node styling, transition and redacted audit summaries, local run-history selection, keyboard-reachable Request/Review/History tabs, and build/test coverage for the graph surface | Continue to checkpoint 5.5 final UI gate |
| 2026-09-14 | Phase 5.3 | Added the Review tab with pending queue refresh, review detail selection, draft/citation/safety reason inspection, reviewer identity and rationale inputs, approve/reject/request-changes actions, stale-action errors, and tests for approval and conflict handling | Continue to checkpoint 5.4 workflow visualization and history |
| 2026-09-14 | Phase 5.2 | Expanded the workflow run UI with status-specific summaries, loading/error handling, sample question entry, final and pending-review answer panels, safety reasons, citations, transitions, audit summaries, local run history, and component coverage for major workflow states | Continue to checkpoint 5.3 review queue and actions |
| 2026-09-14 | Phase 5.1 | Added typed frontend API contracts/client for workflows and review actions, replaced the placeholder with a work-focused clinical-QA request shell, rendered safe workflow result metadata, answers, safety reasons, and citations, and added frontend tests for health/submission/redaction basics | Stop for review before checkpoint 5.2 workflow run experience |
| 2026-09-14 | Phase 5 | Started Product UI work with a checkpointed execution plan covering frontend API contracts, workflow submission/results, review actions, workflow visualization/history, and final UI gates | Complete checkpoint 5.1 UI shell and API contracts |
| 2026-09-13 | Phase 4.5 | Closed Phase 4 with deterministic gates for grounded generation, safety review/block routing, review APIs, restart survival, stale/duplicate/concurrent review protection, redaction, and isolated source handling; updated the Phase 4 live-gate progress map and final roadmap status | Stop for final Phase 4 review before creating the Phase 5 branch |
| 2026-09-13 | Phase 4.4 | Completed concurrency-safe review resume: approval publishes only the exact persisted draft/citations, rejection and request-changes terminate without final output, pending reviews survive restart, and stale/duplicate/concurrent actions cannot resume more than once | Phase 4.5 final gate and documentation |
| 2026-09-13 | Phase 4.3 | Added persisted review queue contracts and API actions with reviewer identity, rationale, policy version, optimistic `review_version`, safe list/detail projections, approve/reject/request-changes handling, and redacted `review_recorded` audit events | Phase 4.4 restart and race-safety gates |
| 2026-09-13 | Phase 4.2.2 | Added post-generation safety as a separate graph node before final response publication; drafts are evaluated under `safety-post-generation-v1`, medication-change language routes to review, diagnosis/prescribing language blocks, grounding signals are required, and only redacted safety metadata is audited | Phase 4.3 persisted review queue and actions |
| 2026-09-13 | Phase 4.2.1 | Added the versioned `safety-precheck-v1` deterministic rule catalog with stable reason IDs, severity, bounded evidence references, medication/allergy conflict review routing, and backend coverage; documented that weak/conflicting evidence stays blocked before generation while draft-specific unsupported recommendation checks move to 4.2.2 | Stop for review before checkpoint 4.2.2 post-generation safety evaluation |
| 2026-08-03 | Phase 4.1.4 | Completed the opt-in real-provider gate with two `gpt-5.4-mini` runs over the locked synthetic patient and reviewed local index; verified strict answers, five exact citations, qualification, routing reproducibility, persistence, redaction, and no failure fallback; separated invalid grounded input from invalid provider output and removed nested retries | Start checkpoint 4.2.1 versioned deterministic safety policy |
| 2026-08-03 | Phase 4.1.3 | Wired configured deterministic/OpenAI generation into LangGraph only after sufficient evidence and safety pass; added bounded relevance-selected facts and excerpts, exact application-owned citations, stable provider failure codes, redacted model/latency/token audit counts, and 280 backend/6 frontend passing tests | Stop for review before checkpoint 4.1.4 opt-in real-provider gate |
| 2026-08-03 | Phase 4.1.2 | Added the official async OpenAI Responses adapter, strict Pydantic answer parsing, stateless/no-tools invocation, bounded validated provider settings, safe SDK failure normalization, and credential-free deterministic tests | Stop for review before checkpoint 4.1.3 grounded prompt and workflow wiring |
| 2026-08-03 | Phase 4.1.1 | Selected OpenAI Responses with `gpt-5.6-sol`, added bounded deidentified grounded-generation contracts, preserved answer-only strict output, defined provider-neutral safe failures, and recorded the prompt-injection boundary | Stop for review before checkpoint 4.1.2 provider adapter and configuration |
| 2026-08-03 | Phase 4 | Started Phase 4 with grounded real-LLM generation as sub-phase 4.1, followed by deterministic/post-generation safety, persisted review actions, concurrency-safe resume, and final gates | Select the first real model provider, then complete checkpoint 4.1.1 contracts and failure policy |
| 2026-08-03 | Phase 3 | Completed reviewed guideline RAG end to end: 2 documents/135 chunks, idempotent Weaviate sync, 9-case retrieval evaluation, seeded five-citation workflow, safe weak/failure routing, persisted redaction, restart recovery, 232 backend/6 frontend tests, and clean source-only verification | Stop for final review before creating the Phase 4 branch |
| 2026-08-03 | Phase 3.6.3 | Made guideline retrieval mandatory for clinical workflows, lazily bound the reviewed local Weaviate retriever, qualified generation with exact application-owned citations, and persisted only the content-free evidence summary plus citation metadata | Stop for review before checkpoint 3.6.4 live and reproducibility gates |
| 2026-08-03 | Phase 3.6.2 | Added the optional LangGraph guideline-retrieval node after patient context, bounded request/result validation, sufficient/review/failure routing, typed retry/timeout behavior, and content-free evidence audit metadata | Stop for review before checkpoint 3.6.3 cited generation and persistence |
| 2026-08-03 | Phase 3.6.1 | Added the content-free workflow evidence summary, strict evidence/citation identity invariants, provider-neutral runtime retrieval capability, and reviewed safe-routing policy without connecting retrieval to LangGraph | Stop for review before checkpoint 3.6.2 graph-node integration |
| 2026-08-03 | Phase 3.3 | Completed strict bounded PDF parsing, deterministic normalization and page-confined chunks, content-free output locking, local build tooling, structural rejection paths, and patient/provider isolation; 164 backend and 6 frontend tests pass, with no embedding or Weaviate changes | Stop for review before sub-phase 3.4 |
| 2026-08-03 | Phase 3.3 | Started parser selection, bounded normalization, stable chunk lineage, deterministic output locking, and malformed/encrypted input handling | Complete the Phase 3.3 gate without embedding or indexing |
| 2026-08-03 | Phase 3.2 | Completed the two-document WHO starter corpus, local-only license decisions, metadata/checksum lock, guarded fetch and offline verification, and deterministic rejection tests; 154 backend and 6 frontend tests pass, with no parsing, embeddings, or Weaviate changes | Stop for review before sub-phase 3.3 |
| 2026-08-03 | Phase 3.2 | Started scenario-driven document selection, exact license/version review, local-only acquisition, and provenance verification | Complete the Phase 3.2 gate without parsing or indexing documents |
| 2026-08-03 | Phase 3.1 | Completed the per-document source and license policy, strict guideline/chunk/retrieval contracts, evidence decisions, citation-lineage validation, provider-neutral retrieval interface, and safe failure boundary; 147 backend and 6 frontend tests pass, with no corpus content acquired | Stop for review before sub-phase 3.2 |
| 2026-08-03 | Phase 3.1 | Started source licensing review, application-owned retrieval contracts, bounded evidence behavior, and provider isolation | Complete the Phase 3.1 review gate without acquiring documents |
| 2026-07-28 | Phase 2.6 | Completed the seeded live workflow/failure gate, persisted-status and redaction proof, bounded cohort-cap reconciliation, clean source-only bootstrap/check, Phase 2 documentation, and Phase 3 review plan; 128 backend and 6 frontend tests pass | Stop for final Phase 2 review before Phase 3 |
| 2026-07-28 | Phase 2.6 | Started the seeded end-to-end, failure-path, reproducibility, isolated-source, and Phase 2 closeout gate | Complete the three Phase 2.6 reviewable steps |
| 2026-07-28 | Phase 2.5 | Completed redacted SQLite checkpoints, synchronous run/status APIs, workflow/correlation/trace identity, bounded capability timeout/retry, interrupted-run recovery, and safe error mappings; 128 backend tests pass | Stop for review before sub-phase 2.6 |
| 2026-07-28 | Phase 2.5 | Started redacted workflow-run persistence, synchronous run/status APIs, bounded capability execution, and interrupted-run recovery | Complete the three Phase 2.5 reviewable steps |
| 2026-07-28 | Phase 2.4 | Completed bounded response generation, application-owned qualification, empty Phase 3 citation enforcement, minimal redacted audit events, safe model failure routing, and deterministic replay; 112 backend tests pass | Stop for review before sub-phase 2.5 |
| 2026-07-28 | Phase 2.4 | Started bounded response-draft and audit boundaries, qualified response generation, and completion routing | Complete the three Phase 2.4 reviewable steps |
| 2026-07-28 | Phase 2.3 | Completed normalized patient retrieval, typed FHIR failure mapping, `initial-safety-v1`, explicit pass/review/block/failure routing, and deterministic boundary coverage; 102 backend tests pass | Stop for review before sub-phase 2.4 |
| 2026-07-28 | Phase 2.3 | Started normalized patient retrieval, typed FHIR failure mapping, a versioned deterministic safety pre-check, and explicit pass/review/block routing | Complete the three Phase 2.3 reviewable steps |
| 2026-07-28 | Phase 2.2 | Completed bounded request contracts, conservative structured intent classification, explicit supported/unknown/failure routing, redaction, and deterministic coverage | Stop for review before sub-phase 2.3 |
| 2026-07-28 | Phase 2.2 | Started bounded request validation, the structured classifier boundary, deterministic intent classification, and explicit routing outcomes | Complete the three Phase 2.2 reviewable steps |
| 2026-07-28 | Phase 2.1 | Completed typed graph state, lifecycle rules, transition reducer, run-scoped clock, safely terminating async LangGraph skeleton, and deterministic replay coverage | Stop for review before sub-phase 2.2 |
| 2026-07-28 | Phase 2.1 | Started execution contracts, transition and reducer semantics, run-scoped dependencies, and a safely terminating LangGraph skeleton | Complete the three Phase 2.1 reviewable steps |
| 2026-07-27 | Phase 1 | Final review accepted after the Phase 1.6 changes were committed; all Phase 1 scope and exit criteria remain complete | Create the Phase 2 branch, then begin sub-phase 2.1 when requested |
| 2026-07-27 | Phase 1.6 | Completed the normalized patient API, safe FHIR error mapping, live seed-to-query and missing-patient checks, local and isolated-source gates, documentation, and Phase 2 sub-phase plan | Stop for final Phase 1 review before Phase 2 |
| 2026-07-27 | Phase 1.6 | Started the normalized summary API boundary, end-to-end failure verification, reproducibility gate, and Phase 2 handoff plan | Complete the three Phase 1.6 reviewable steps |
| 2026-07-27 | Phase 1.5 | Completed minimum-necessary patient summaries, seven-category normalization, deterministic ordering, explicit truncation, partial-record tests, and a live seeded-patient smoke check | Stop for review before sub-phase 1.6 |
| 2026-07-27 | Phase 1.5 | Started the minimum-necessary summary contract, bounded multi-resource retrieval, normalization, and partial-record tests | Complete the three Phase 1.5 reviewable steps |
| 2026-07-27 | Phase 1.4 | Completed the read-only FHIR protocol, bounded async HAPI adapter, typed safe failures, confined pagination, deterministic transport tests, and live read/search smoke check | Stop for review before sub-phase 1.5 |
| 2026-07-27 | Phase 1.4 | Started the application-owned read-only FHIR interface, bounded HAPI transport, typed failures, and deterministic transport tests | Complete the three Phase 1.4 reviewable steps |
| 2026-07-27 | Phase 1.3 | Completed loopback-only idempotent HAPI seeding, exact resource/patient verification, contamination refusal, confirmed HAPI-only reset, recovery, and pgAdmin safety documentation | Stop for review before sub-phase 1.4 |
| 2026-07-27 | Phase 1.3 | Started loopback-only HAPI target safeguards, reset, idempotent transaction seeding, and post-import verification | Implement and test the three Phase 1.3 reviewable steps |
| 2026-07-27 | Phase 1.2 | Kept all generated FHIR content local and ignored; added a metadata-only checksum lock that reproduces and verifies the four reviewed selections exactly | Stop for review before sub-phase 1.3 |
| 2026-07-27 | Phase 1.2 | Completed pinned deterministic generation, four reviewed local FHIR fixtures, manifest integrity checks, and byte-for-byte repeatability verification; no HAPI import performed | Decide whether generated fixtures belong in Git |
| 2026-07-27 | Phase 1.2 | Started pinned Synthea execution, deterministic candidate generation, fixture selection, and review tooling | Generate and review the four contracted FHIR bundles |
| 2026-07-27 | Phase 1.1 | Completed the four-patient cohort contract, pinned Synthea provenance and deterministic inputs, and defined resource, manifest, review, and size requirements; no patient data generated | Stop for review before sub-phase 1.2 |
| 2026-07-27 | Phase 1.1 | Started the synthetic cohort contract and provenance work on the Phase 1 branch | Pin Synthea inputs and define reviewed cohort scenarios |
| 2026-07-27 | Phase 0 | Completed all foundation scope and exit criteria; isolated setup, local quality gates, smoke tests, and the GitHub Quality workflow pass | Create the Phase 1 branch, then begin sub-phase 1.1 |
| 2026-07-27 | Phase 0.6 | Completed local foundation documentation and isolated source verification; fixed configurable dev ports and frontend argument forwarding found by startup smoke tests | Commit and push Phase 0.6, then confirm the GitHub Quality workflow is green |
| 2026-07-27 | Phase 0.6 | Started the documentation, clean-environment verification, and foundation handoff gate | Complete documentation, verify isolated setup, and prepare Phase 1 plan |
| 2026-07-27 | Phase 0.5 | Completed local backend/frontend quality gates, project-local pre-commit hooks, lockfile-based CI jobs and safe dependency caching; verified a deliberate lint failure is rejected | Stop for review before sub-phase 0.6 |
| 2026-07-27 | Phase 0.5 | Started backend/frontend quality gates, pre-commit hooks, and CI automation | Verify every gate and stop for review |
| 2026-07-27 | Phase 0.4 | Exposed HAPI PostgreSQL on loopback port 5434 for local pgAdmin access and documented the connection settings | Stop for review before sub-phase 0.5 |
| 2026-07-27 | Phase 0.4 | Completed pinned local infrastructure, persistence, health checks, lifecycle commands, and dependency-aware backend readiness | Stop for review before sub-phase 0.5 |
| 2026-07-27 | Phase 0.4 | Started local infrastructure and dependency-readiness work | Inventory local images and implement reproducible services |
| 2026-07-27 | Phase 0.3 | Moved backend environment template to `backend/.env.example` and documented the ignored `backend/.env` local copy | Review before sub-phase 0.4 |
| 2026-07-27 | Phase 0.3 | Completed validated configuration and strict provider-neutral workflow, API, clinical, safety, and audit contracts | Stop for review before sub-phase 0.4 |
| 2026-07-27 | Phase 0.3 | Started typed contracts and validated configuration | Implement schemas and configuration, then verify their failure behavior |
| 2026-07-27 | Phase 0.2 | Fixed Makefile backend commands to bootstrap and use a pinned project-local `uv` | Re-run `make backend-sync`, then review before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Added a root Makefile for setup, development servers, tests, and frontend builds; completed the related Phase 0.5 task early | Review Makefile commands before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Completed and verified FastAPI and React/Vite application skeletons with locked dependencies and smoke tests | Stop for review before sub-phase 0.3 |
| 2026-07-27 | Phase 0.2 | Started backend and frontend application skeletons | Build and verify the minimal application shells |
| 2026-07-27 | Phase 0.1 | Completed MVP scope, foundation decisions, module boundaries, and development safety policy | Stop for review before sub-phase 0.2 |
| 2026-07-27 | Phase 0.1 | Started scope and technical-decision work on `create-foundations` | Document and review the MVP boundaries and foundation choices |
| 2026-07-27 | Phase 0 | Added the Phase 0 sub-phase plan for implementation on `create-foundations` | Review and begin sub-phase 0.1 |
| 2026-07-27 | Planning | Selected Weaviate instead of Qdrant for guideline retrieval | Confirm the local image version and Docker configuration during Phase 0 |
| 2026-07-27 | Planning | Converted the original concept into this phased delivery roadmap | Review Phase 0 scope and begin repository scaffolding |
