# Phase 3 — Clinical Guidelines RAG Plan

This plan divides Phase 3 of the
[project roadmap](PROJECT_ROADMAP.md) into reviewable checkpoints. It prepares
the next phase only; no guideline corpus, Weaviate schema, ingestion, retrieval,
or workflow integration is implemented by the Phase 2 gate.

## Objective

Ground the existing qualified clinical-QA response in a small, reviewed
guideline corpus with traceable citations, deterministic retrieval behavior,
and explicit failure when evidence is missing or unsafe.

## Prerequisites

- Phase 2 is accepted and its seeded synthetic workflow gate passes.
- Weaviate remains reachable only as a local development dependency.
- The existing `Citation`, `GeneratedResponse`, workflow, safety, audit, and
  redacted persistence contracts remain provider-neutral.
- Corpus source approval and licensing must precede document download or
  ingestion.

## Tracking

| Sub-phase | Deliverable | Status |
|---|---|---|
| 3.1 Source policy and retrieval contracts | Allowed sources, licenses, document metadata, retrieval requests/results, and safe failures are explicit | `[x]` |
| 3.2 Reviewed starter corpus | A small checksum-locked corpus has provenance, license notes, and no patient data | `[ ]` |
| 3.3 Deterministic parsing and chunking | Approved documents become bounded, stable chunks with page/section lineage | `[ ]` |
| 3.4 Weaviate schema and idempotent ingestion | Replaceable vector-store interfaces support verified local indexing and reset | `[ ]` |
| 3.5 Retrieval and citation qualification | Clinical queries return bounded relevant chunks and application-owned citations or fail safely | `[ ]` |
| 3.6 Workflow integration and Phase 3 gate | The graph retrieves evidence before generation and completes a cited seeded scenario reproducibly | `[ ]` |

## Sub-phase 3.1 — Source Policy and Retrieval Contracts

- `[x]` Define allowed publishers, document types, recency/version metadata, and
  explicit license-review fields.
- `[x]` Define application-owned document, chunk, retrieval-query, retrieval-result,
  and typed failure contracts.
- `[x]` Bound query length, result count, chunk size, metadata, and excerpts.
- `[x]` Decide how missing, stale, conflicting, or insufficient evidence affects
  workflow status and safety review.
- `[x]` Test strict parsing, unknown fields, bounds, and provider-object isolation.

Source and licensing decisions are defined in the
[guideline source policy](GUIDELINE_SOURCE_POLICY.md). Publisher eligibility
does not grant content reuse: every document needs an explicit use-permission
decision before acquisition or indexing.

**Review checkpoint:** approve sources, licensing fields, evidence sufficiency,
and contract ownership before acquiring documents.

### Verification Record

Verified on 2026-08-03:

- Limited initial candidates to WHO, CDC, NICE, and ADA while separating
  publisher authority from an exact per-document content-use decision.
- Recorded format, publication/version/access metadata, license review,
  lifecycle, checksum, and supported-topic requirements. NICE and ADA default
  to link-only until applicable permission is verified.
- Added strict application-owned source, chunk, retrieval request/match/result,
  evidence assessment, and citation-lineage contracts.
- Limited deidentified clinical queries to 1,000 characters, top-k results to
  eight, chunk text to 3,000 characters, and citation excerpts to 500
  characters.
- Added a provider-neutral async retrieval protocol and distinct timeout,
  unavailable, and malformed-response failures. An empty `insufficient`
  result remains a valid outcome rather than an infrastructure error.
- Added focused tests for allowlists, permissions, lifecycle, chronology,
  bounds, strict unknown-field rejection, provider-object isolation,
  deterministic ranks, evidence states, and source/chunk/citation lineage.
- `make check` passed with 147 backend and 6 frontend tests, the frontend
  production build, and Compose validation.
- No document was downloaded, parsed, committed, embedded, or indexed; those
  actions remain behind the sub-phase 3.2 review gate.

**Status:** `[x]` Complete — stop for review before sub-phase 3.2.

## Sub-phase 3.2 — Reviewed Starter Corpus

- Select a minimal scenario-driven corpus from approved authoritative sources.
- Record canonical URL, publisher, title, version/date, access date, license or
  usage note, checksum, and supported scenario for every document.
- Keep downloads/generated extraction output out of Git unless redistribution
  is explicitly permitted; commit non-content provenance/checksum locks.
- Add verification that rejects missing, changed, unapproved, or oversized
  inputs.

**Review checkpoint:** inspect every source and its redistribution decision
before parsing or indexing.

## Sub-phase 3.3 — Deterministic Parsing and Chunking

- Parse only approved formats with bounded resource usage.
- Normalize text without losing page, heading, section, or document lineage.
- Produce stable chunk IDs and deterministic order from content checksums.
- Reject empty, malformed, unexpectedly encrypted, or structurally unsafe
  documents.
- Test repeated parsing, chunk boundaries, metadata lineage, and absence of
  patient data.

**Review checkpoint:** review representative chunks and citation lineage before
creating a vector schema.

## Sub-phase 3.4 — Weaviate Schema and Idempotent Ingestion

- Define a vector-store protocol before implementing the Weaviate adapter.
- Use an application-owned collection name, schema version, stable object IDs,
  and metadata filters.
- Make ingestion idempotent and verify exact document/chunk/checksum counts.
- Add a guarded reset that affects only the application guideline collection.
- Keep anonymous access documented as loopback-only development behavior.

**Review checkpoint:** inspect schema, embedding boundary, idempotency, and
reset targeting before retrieval is connected.

## Sub-phase 3.5 — Retrieval and Citation Qualification

- Retrieve a small bounded top-k set with deterministic tie-breaking and
  approved metadata filters.
- Normalize results into application-owned chunks and `Citation` values.
- Prevent the model from inventing or altering citation identity.
- Define explicit no-evidence, weak-evidence, timeout, unavailable, and
  malformed-result outcomes.
- Test relevance fixtures, stable ordering, citation URLs/pages, redaction,
  timeout, and provider isolation.

**Review checkpoint:** approve retrieval quality and no-evidence behavior before
the graph can use guideline results.

## Sub-phase 3.6 — Workflow Integration and Phase 3 Gate

- Insert guideline retrieval after patient context and before response
  generation at a reviewed safety boundary.
- Permit guideline-backed claims only when application-owned citations exist.
- Audit document/chunk identifiers and counts without storing full document
  bodies, queries, prompts, or provider payloads.
- Run deterministic, live Weaviate, failure-path, restart, and isolated-source
  gates.
- Update architecture, development, contracts, safety policy, and roadmap
  status.

## Phase Exit Criteria

- A seeded synthetic clinical-QA run completes with at least one verified
  citation from an approved guideline.
- Citation metadata resolves to the exact indexed document location.
- Missing, weak, unavailable, malformed, or conflicting evidence fails safely
  or requires review without fabricated claims.
- Re-ingestion and retrieval are deterministic and idempotent.
- No patient data enters the corpus, vector metadata, embeddings, or committed
  fixtures.
- Repository, live retrieval, and isolated-source quality gates pass.
