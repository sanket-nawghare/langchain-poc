# Phase 4 — Grounded Generation, Safety, and Human Review Plan

This plan makes provider-backed grounded generation explicit before adding
human approval and resume behavior. Every checkpoint is independently
reviewable and must finish with focused tests and `make check`.

## Objectives

- Generate answer drafts with a configured LLM using only bounded synthetic
  patient context and validated guideline evidence.
- Keep citations, disclaimers, routing, and safety decisions application-owned.
- Pause risky, ambiguous, weak, or unsupported outputs for attributable human
  review.
- Resume only the exact persisted checkpoint after a valid review action.
- Preserve the repository's synthetic-only, redacted, provider-neutral
  boundaries.

## Tracking

| Sub-phase | Deliverable | Status |
|---|---|---|
| 4.1 Grounded LLM response generation | A configured provider drafts structured answers from bounded patient context and retrieved evidence | `[~]` |
| 4.2 Deterministic and LLM-assisted safety | Versioned rules evaluate inputs, evidence, and generated drafts without delegating final safety authority to the model | `[ ]` |
| 4.3 Persisted review queue and actions | Reviewers can inspect safe metadata and approve, reject, or request changes | `[ ]` |
| 4.4 Concurrency-safe resume | Valid review actions resume the exact checkpoint once and reject stale or duplicate actions | `[ ]` |
| 4.5 Phase 4 integration gate | Grounded generation, review, restart, authorization, redaction, and isolated-source gates pass | `[ ]` |

## Sub-phase 4.1 — Grounded LLM Response Generation

### 4.1.1 — Provider Decision and Grounded Contracts

- `[~]` Select the first real model provider and record its model/API/version
  assumptions without coupling domain contracts to its SDK.
- `[ ]` Define the bounded grounded-generation input: clinical question,
  minimum necessary normalized synthetic patient context, and ranked trusted
  citation excerpts.
- `[ ]` Keep provider output restricted to `ResponseDraft.answer`; reject
  provider citations, disclaimers, tool calls, or unknown fields.
- `[ ]` Define safe timeout, unavailable, authentication, rate-limit,
  malformed-output, and context-limit failures.
- `[ ]` Specify prompt-injection handling and ensure retrieved text cannot
  change tools, routing, citations, safety policy, or system instructions.

### 4.1.2 — Provider Adapter and Configuration

- `[ ]` Implement one provider adapter behind the existing
  `ResponseGenerator` protocol.
- `[ ]` Add validated provider, model, endpoint, timeout, retry, and secret
  configuration with deterministic fake defaults for tests.
- `[ ]` Parse structured output strictly and discard provider identifiers,
  token payloads, raw responses, and exception details at the adapter boundary.
- `[ ]` Test success, authentication, rate-limit, timeout, unavailable,
  malformed, oversized, and unexpected provider behavior.

### 4.1.3 — Grounded Prompt and Workflow Wiring

- `[ ]` Build the prompt only after sufficient retrieval evidence and the
  deterministic safety pre-check pass.
- `[ ]` Send bounded citation excerpts rather than full source documents or
  vector-store/provider objects.
- `[ ]` Require the final response to reuse the exact application-owned
  citations supplied to the model.
- `[ ]` Prevent model invocation for unsupported intent, missing/weak/
  conflicting evidence, safety review/block, or invalid patient context.
- `[ ]` Audit only provider-neutral outcome, model alias, latency/token counts
  when available, and citation count; never prompt or response bodies.

### 4.1.4 — Real-Provider Gate

- `[ ]` Add an opt-in live gate using only a seeded synthetic patient and the
  reviewed local guideline index.
- `[ ]` Verify the response is structured, cited, qualified, reproducible at
  the routing level, and contains no fabricated citation identity.
- `[ ]` Verify provider failure never falls back to an uncited deterministic
  clinical answer.
- `[ ]` Keep deterministic tests and basic startup independent of credentials
  and external model availability.

## Sub-phase 4.2 — Deterministic and LLM-Assisted Safety

### 4.2.1 — Versioned Safety Policy

- `[ ]` Define severity, rule identifiers, evidence references, and policy
  versioning for pre-generation and post-generation checks.
- `[ ]` Cover urgent language, medication/allergy conflicts, missing or
  truncated context, unsupported recommendations, and evidence disagreement.

### 4.2.2 — Post-Generation Safety Evaluation

- `[ ]` Evaluate the grounded draft separately from deterministic input rules.
- `[ ]` Allow an LLM-assisted signal only as structured evidence for
  application-owned deterministic routing.
- `[ ]` Route pass, review, and block outcomes explicitly without silently
  rewriting generated content.

## Sub-phase 4.3 — Persisted Review Queue and Actions

### 4.3.1 — Review Contracts and Redacted Queue

- `[ ]` Define review item, action, rationale, reviewer identity, policy
  version, and optimistic-concurrency contracts.
- `[ ]` Persist only the safe review projection needed for an attributable
  decision.

### 4.3.2 — Review API

- `[ ]` Add list/detail endpoints for pending review and approve, reject, and
  request-changes actions.
- `[ ]` Validate authorization boundaries and reject missing, invalid, stale,
  or duplicate actions without revealing hidden workflow state.

## Sub-phase 4.4 — Concurrency-Safe Resume

### 4.4.1 — Durable Checkpoint Resume

- `[ ]` Persist the exact resumable graph checkpoint and review version.
- `[ ]` Resume only after approval; rejection terminates and request-changes
  follows an explicit bounded route.

### 4.4.2 — Restart and Race Safety

- `[ ]` Prove pending work survives restart without automatic execution.
- `[ ]` Prove concurrent, duplicate, stale, or replayed actions cannot resume a
  workflow more than once.

## Sub-phase 4.5 — Phase Gate and Documentation

- `[ ]` Run deterministic and opt-in real-provider happy, review, block,
  failure, restart, concurrency, redaction, and isolated-source gates.
- `[ ]` Update architecture, contracts, safety policy, development guide, and
  roadmap status.
- `[ ]` Stop for final Phase 4 review before Phase 5 UI work.

## Phase Exit Criteria

- A real configured LLM receives bounded patient context and trusted retrieved
  excerpts and returns a strictly parsed answer draft.
- Every completed answer uses application-owned citations and disclaimer.
- High-risk or ambiguous cases cannot bypass deterministic review routing.
- Review actions are attributable, versioned, persisted, and concurrency-safe.
- Pending review survives restart and resumes exactly once after valid approval.
- No prompts, patient context, retrieved bodies, provider payloads, or secrets
  enter audit logs or unsafe persisted fields.
