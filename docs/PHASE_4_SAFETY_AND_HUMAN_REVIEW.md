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
| 4.1 Grounded LLM response generation | A configured provider drafts structured answers from bounded patient context and retrieved evidence | `[x]` |
| 4.2 Deterministic and LLM-assisted safety | Versioned rules evaluate inputs, evidence, and generated drafts without delegating final safety authority to the model | `[ ]` |
| 4.3 Persisted review queue and actions | Reviewers can inspect safe metadata and approve, reject, or request changes | `[ ]` |
| 4.4 Concurrency-safe resume | Valid review actions resume the exact checkpoint once and reject stale or duplicate actions | `[ ]` |
| 4.5 Phase 4 integration gate | Grounded generation, review, restart, authorization, redaction, and isolated-source gates pass | `[ ]` |

## Sub-phase 4.1 — Grounded LLM Response Generation

### 4.1.1 — Provider Decision and Grounded Contracts

- `[x]` Select the first real model provider and record its model/API/version
  assumptions without coupling domain contracts to its SDK.
- `[x]` Define the bounded grounded-generation input: clinical question,
  minimum necessary normalized synthetic patient context, and ranked trusted
  citation excerpts.
- `[x]` Keep provider output restricted to `ResponseDraft.answer`; reject
  provider citations, disclaimers, tool calls, or unknown fields.
- `[x]` Define safe timeout, unavailable, authentication, rate-limit,
  malformed-output, and context-limit failures.
- `[x]` Specify prompt-injection handling and ensure retrieved text cannot
  change tools, routing, citations, safety policy, or system instructions.

#### Reviewed provider assumptions

- **Provider:** OpenAI is the first adapter; domain and workflow contracts remain
  independent of the OpenAI SDK.
- **API/model:** use the Responses API at `/v1/responses` with
  `gpt-5.6-sol`, the current flagship model selected on 2026-08-03. Revisit the
  model at the opt-in live gate rather than silently changing it during an SDK
  upgrade.
- **Invocation:** one stateless request with provider storage disabled, no
  provider tools, bounded output, and a deliberately configured reasoning
  effort. SDK/version and runtime settings belong to checkpoint 4.1.2.
- **Output:** use Responses structured parsing against the strict
  application-owned `ResponseDraft` schema. A refusal, missing parsed object,
  extra field, oversized answer, or non-message output is not a valid draft.
- **Data boundary:** the provider receives one question of at most 1,000
  characters, 1–32 deidentified normalized clinical facts, and 1–8 ordered
  application-owned citations whose excerpts are each at most 500 characters.
  Patient ID, display name, raw FHIR resources, full guideline chunks, and
  workflow/audit state are excluded.

Official assumptions were checked against the OpenAI
[model guidance](https://developers.openai.com/api/docs/guides/latest-model),
[GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
and [structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

#### Prompt-injection boundary

- The clinical question, facts, and evidence excerpts are untrusted data, never
  instructions. The adapter must serialize and delimit them separately from the
  application-owned system policy.
- Retrieved text cannot add or call tools, change routing, replace citation
  identities or the disclaimer, weaken safety rules, or request hidden state.
  No tools will be exposed to the generation request.
- The model drafts answer text only. Strict parsing and post-generation safety
  checks remain mandatory; model output is not trusted merely because it matches
  the schema.
- Provider errors are normalized to timeout, unavailable, authentication,
  rate-limit, malformed-output, context-limit, or refusal failures. Raw provider
  payloads and exception details do not cross the adapter boundary.

### 4.1.2 — Provider Adapter and Configuration

- `[x]` Implement one provider adapter behind the existing
  `ResponseGenerator` protocol.
- `[x]` Add validated provider, model, endpoint, timeout, retry, and secret
  configuration with deterministic fake defaults for tests.
- `[x]` Parse structured output strictly and discard provider identifiers,
  token payloads, raw responses, and exception details at the adapter boundary.
- `[x]` Test success, authentication, rate-limit, timeout, unavailable,
  malformed, oversized, and unexpected provider behavior.

The adapter is implemented and independently testable. Runtime selection,
generation timing, citation preservation, and redacted audit metadata are
completed in checkpoint 4.1.3.

### 4.1.3 — Grounded Prompt and Workflow Wiring

- `[x]` Build the prompt only after sufficient retrieval evidence and the
  deterministic safety pre-check pass.
- `[x]` Send bounded citation excerpts rather than full source documents or
  vector-store/provider objects.
- `[x]` Require the final response to reuse the exact application-owned
  citations supplied to the model.
- `[x]` Prevent model invocation for unsupported intent, missing/weak/
  conflicting evidence, safety review/block, or invalid patient context.
- `[x]` Audit only provider-neutral outcome, model alias, latency/token counts
  when available, and citation count; never prompt or response bodies.

The workflow now selects the configured generator at request scope and builds a
strict data-only request only on the sufficient-evidence, safety-pass path. A
deterministic relevance selector sends at most 32 normalized facts without
patient identifiers or clinical codes, plus at most eight exact ranked citation
excerpts. The application—not the provider—attaches the original citations and
educational disclaimer. Only temporary unavailable/rate-limit failures retry;
all provider failures terminate with stable redacted workflow codes.

### 4.1.4 — Real-Provider Gate

- `[x]` Add an opt-in live gate using only a seeded synthetic patient and the
  reviewed local guideline index.
- `[x]` Verify the response is structured, cited, qualified, reproducible at
  the routing level, and contains no fabricated citation identity.
- `[x]` Verify provider failure never falls back to an uncited deterministic
  clinical answer.
- `[x]` Keep deterministic tests and basic startup independent of credentials
  and external model availability.

`make phase4-generation-live-gate` verifies the locked synthetic cohort, all
nine local retrieval cases, and two real-provider workflow runs without making
the live gate part of normal CI. On 2026-08-03 the gate passed with the locally
configured `gpt-5.4-mini`: both runs returned strict answers, the same five
application-owned citation identities and routing history, the educational
qualification, persisted redacted snapshots, and content-free audit metadata.
Credential-free contract tests prove every provider failure terminates without
a deterministic or uncited fallback.

Live validation also found that two normalized observation values exceeded the
grounded request's stricter field size. The selector now truncates each allowed
field deterministically at its contract boundary, and pre-provider input
failures use `response_generation_invalid_input` rather than being mislabeled
as model output failures. Provider retries now have one owner: the OpenAI SDK
does not retry internally, while LangGraph applies the configured LLM timeout
and retry budget once.

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
