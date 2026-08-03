# Phase 3 — Clinical Guidelines RAG Plan

This plan divides Phase 3 of the
[project roadmap](PROJECT_ROADMAP.md) into reviewable checkpoints and records
the accepted boundary after each sub-phase.

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
| 3.2 Reviewed starter corpus | A small checksum-locked corpus has provenance, license notes, and no patient data | `[x]` |
| 3.3 Deterministic parsing and chunking | Approved documents become bounded, stable chunks with page/section lineage | `[x]` |
| 3.4 Weaviate schema and idempotent ingestion | Replaceable vector-store interfaces support verified local indexing and reset | `[x]` |
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

- `[x]` Select a minimal scenario-driven corpus from approved authoritative sources.
- `[x]` Record canonical URL, publisher, title, version/date, access date, license or
  usage note, checksum, and supported scenario for every document.
- `[x]` Keep downloads/generated extraction output out of Git unless redistribution
  is explicitly permitted; commit non-content provenance/checksum locks.
- `[x]` Add verification that rejects missing, changed, unapproved, or oversized
  inputs.

**Review checkpoint:** inspect every source and its redistribution decision
before parsing or indexing.

### Verification Record

Verified on 2026-08-03:

- Selected WHO HEARTS-D (2020) for `metabolic-01` and the WHO adult
  hypertension guideline (2021) for `cardiovascular-01`.
- Reviewed each PDF copyright page and official publication record. Both state
  CC BY-NC-SA 3.0 IGO; the repository adopts a conservative
  `local_index_only` decision with required attribution, no implied WHO
  endorsement/logo use, and exclusion of separately owned third-party
  material.
- Committed only strict provenance, license, scenario, size, page-count, and
  SHA-256 metadata. Both downloaded PDFs are ignored.
- Added `make guidelines-fetch` for guarded acquisition from exact approved
  WHO endpoints and `make guidelines-verify` for offline integrity checks.
- Verified two exact PDF artifacts totaling 2,091,637 bytes. Acquisition
  refuses unapproved sources or permissions, unsafe names, unexpected files,
  malformed PDF envelopes, files over 4 MiB, and size/checksum drift.
- Added deterministic failure tests for missing, unexpected, changed,
  malformed, oversized, unapproved, and provider-specific inputs.
- `make check` passed with 154 backend and 6 frontend tests, the frontend
  production build, and Compose validation.
- No text was extracted, chunked, embedded, committed, or indexed, and
  Weaviate remains unchanged.

**Status:** `[x]` Complete — stop for review before sub-phase 3.3.

## Sub-phase 3.3 — Deterministic Parsing and Chunking

- `[x]` Parse only approved formats with bounded resource usage.
- `[x]` Normalize text without losing page, heading, section, or document lineage.
- `[x]` Produce stable chunk IDs and deterministic order from content checksums.
- `[x]` Reject empty, malformed, unexpectedly encrypted, or structurally unsafe
  documents.
- `[x]` Test repeated parsing, chunk boundaries, metadata lineage, and absence of
  patient data.

**Review checkpoint:** review representative chunks and citation lineage before
creating a vector schema.

### Verification Record

Verified on 2026-08-03:

- Locked pypdf 6.14.2 behind the application-owned `GuidelineDocumentParser`
  capability and typed input, encrypted, malformed, and bounds failures.
- Added `deterministic-pypdf-v1`: strict PDF parsing, Unicode/whitespace
  normalization, conservative heading hints, page-confined 2,400-character
  chunks, stable content hashes/IDs, and contiguous document sequences.
- Bounded source files, page count, extracted page/document text, chunk size,
  chunk count, catalog actions, attachments, and encrypted inputs. Source
  checksum and reviewed page count are revalidated before extraction.
- Produced 40 chunks for HEARTS-D and 95 for the hypertension guideline. The
  ignored strict output is 280,499 bytes; the committed chunk lock contains no
  extracted text.
- Repeated parsing produces byte-equivalent provider-neutral output. Tests
  cover normalization, chunk boundaries, page/section/document lineage,
  checksum and page drift, empty/malformed/encrypted PDFs, JavaScript,
  attachments, oversized extraction, strict output reload, lock drift, and
  provider-field rejection.
- The generated output contains no patient contract fields and matches none of
  the local synthetic cohort IDs or aliases.
- Reviewed extractable text for separately attributed reuse markers; none were
  found. The parser extracts no images, and separately owned material remains
  prohibited by the source policy.
- `make check` passed with 164 backend and 6 frontend tests, the frontend
  production build, and Compose validation.
- No embeddings or Weaviate schema, objects, or calls were added.

**Status:** `[x]` Complete — stop for review before sub-phase 3.4.

## Sub-phase 3.4 — Weaviate Schema and Idempotent Ingestion

- `[x]` Define a vector-store protocol before implementing the Weaviate adapter.
- `[x]` Use an application-owned collection name, schema version, stable object IDs,
  and metadata filters.
- `[x]` Make ingestion idempotent and verify exact document/chunk/checksum counts.
- `[x]` Add a guarded reset that affects only the application guideline collection.
- `[x]` Keep anonymous access documented as loopback-only development behavior.

**Review checkpoint:** inspect schema, embedding boundary, idempotency, and
reset targeting before retrieval is connected.

### Verification Record

Verified on 2026-08-03:

- Pinned `weaviate-client` 4.22.x and defined provider-neutral embedding,
  vector-record, index-snapshot, ingestion-result, and vector-store contracts
  with typed unavailable, schema, write, and verification failures.
- Added `ClinicalGuidelineChunkV1` with explicit self-provided cosine vectors,
  schema version 1, searchable title/section/text, and filterable source,
  lifecycle, topic, page, sequence, version, and checksum metadata.
- Stable UUIDv5 identity includes schema, parser, embedding model, chunk ID,
  and content checksum. The local `deterministic-token-hash-v1` implementation
  produces bounded repeatable 128-dimensional unit vectors and can be replaced
  without changing domain or store interfaces.
- Added exact insert/replace/skip/stale-delete planning. Expected writes happen
  before stale deletes; every sync finishes by comparing all application
  object IDs and metadata and deriving exact document/chunk/source-checksum
  counts.
- Added `make guidelines-index`, `make guidelines-index-verify`, and a reset
  requiring `CONFIRM=1` plus the exact compiled collection name. The command
  accepts only loopback HTTP Weaviate configuration and never targets another
  collection.
- Live ingestion inserted 135 chunks from two checksum-locked documents. A
  second run skipped all 135, one controlled drift was replaced, reset refused
  without confirmation, and confirmed collection-only reset rebuilt and
  verified the exact 2-document/135-chunk snapshot.
- `make check` passed with 174 backend and 6 frontend tests, strict backend and
  frontend static checks, the frontend production build, and Compose
  validation.
- Retrieval queries, ranking, evidence thresholds, citations, and workflow
  integration remain unchanged and deferred to sub-phases 3.5 and 3.6.

**Status:** `[x]` Complete — stop for review before sub-phase 3.5.

## Sub-phase 3.5 — Retrieval and Citation Qualification

### Tracking

| Checkpoint | Deliverable | Status |
|---|---|---|
| 3.5.1 Retrieval trust policy and candidate contracts | Candidate bounds, source-of-truth rules, deterministic ordering inputs, and provider-neutral search contracts are explicit | `[x]` |
| 3.5.2 Trusted catalog and Weaviate candidate adapter | Eligible sources come from the committed lock and filtered vector candidates normalize safely | `[ ]` |
| 3.5.3 Evidence qualification and citations | Calibrated deterministic scores produce trusted citations or explicit insufficient/conflicting results | `[ ]` |
| 3.5.4 Retrieval gate and documentation | Fixture relevance, live queries, failures, redaction, and complete quality gates pass | `[ ]` |

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

Detailed trust, filtering, scoring, and failure rules are recorded in the
[guideline retrieval policy](GUIDELINE_RETRIEVAL_POLICY.md).

### Checkpoint 3.5.1 Verification Record

Verified on 2026-08-03:

- Established the committed corpus lock—not Weaviate—as the authority for
  provenance, permission, lifecycle, source identity, and citation fields.
- Defined a two-stage boundary: application code derives eligible trusted
  document IDs, then the vector store returns only bounded normalized chunk
  candidates for later source hydration and qualification.
- Added strict application-owned vector-search request and candidate contracts
  with exact model/dimension identity, finite nonzero query vectors, at most
  eight eligible documents, at most 32 candidates, bounded cosine distance,
  stable object/chunk lineage, and no patient or provider fields.
- Froze eligibility, metadata-drift rejection, deterministic tie-breaking
  inputs, query-fingerprint handling, evidence outcomes, and safe failure rules.
  Exact relevance scoring and thresholds remain intentionally deferred until
  fixture calibration in checkpoint 3.5.3.
- Added a provider-neutral asynchronous candidate-store protocol. No Weaviate
  query implementation, ranking, citation construction, workflow state, or
  LangGraph behavior changed in this checkpoint.
- `make check` passed with 179 backend and 6 frontend tests, strict backend and
  frontend static checks, the frontend production build, and Compose
  validation.

**Status:** `[x]` Complete — stop for review before checkpoint 3.5.2.

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
