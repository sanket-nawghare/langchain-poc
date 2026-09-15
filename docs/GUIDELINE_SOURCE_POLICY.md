# Guideline Source and Evidence Policy

## Scope

This policy governs every clinical-guideline document considered for the local
RAG corpus. It separates publisher authority from permission to copy or index
content: an allowed publisher is only eligible for review, and no document is
approved automatically.

Phase 3 uses guideline content only for the educational synthetic-patient
workflow. It does not make the application a source of medical advice.

## Candidate Publishers

The initial allowlist is deliberately small:

| Publisher | Authority decision | Default use decision | Required review |
|---|---|---|---|
| World Health Organization (WHO) | Allowed candidate | Per-document review | Check the publication's copyright notice, license terms, permitted purpose, attribution, and third-party content |
| Centers for Disease Control and Prevention (CDC) | Allowed candidate | Per-item review | Confirm whether the item is a US Government work or separately copyrighted; record attribution and non-endorsement requirements |
| National Institute for Health and Care Excellence (NICE) | Allowed candidate | Link only | Because this project is outside the UK, obtain the applicable international permission before copying or indexing content |
| American Diabetes Association (ADA) | Allowed candidate | Link only | Obtain explicit permission or verify a document-specific license before copying or indexing content |

The authoritative terms reviewed for this decision are:

- [WHO copyright and licensing](https://www.who.int/about/policies/publishing/copyright)
- [CDC use of agency materials](https://www.cdc.gov/other/agencymaterials.html)
- [CDC Stacks content and copyright](https://stacks.cdc.gov/Content%20and%20Copyright)
- [NICE reuse guidance](https://www.nice.org.uk/reusing-our-content)
- [NICE terms and conditions](https://www.nice.org.uk/terms-and-conditions)
- [ADA terms of use](https://diabetes.org/about-us/policies/terms-of-use)
- [ADA journal permissions](https://diabetesjournals.org/journals/pages/permissions)

Terms can change. The review records the exact canonical URL, license URL,
access date, reviewer decision, and content checksum used for each document.

## Document Approval

Only English HTML or PDF guideline documents are eligible in the initial
corpus. Every candidate must record:

- application-owned document ID, title, publisher, canonical URL, and format;
- publication date, named version, access date, and lifecycle status;
- license name and URL when available;
- one explicit use permission: `redistribute_and_index`, `local_index_only`,
  `link_only`, or `prohibited`;
- license review date and a bounded review note;
- SHA-256 checksum and supported clinical topics.

Only `redistribute_and_index` and `local_index_only` content may enter the
local parser, chunker, embeddings, or Weaviate collection. `link_only` stores
provenance metadata without downloading content. `prohibited` content is
rejected. Current status is also required: superseded or withdrawn documents
are not retrievable evidence.

Redistributable content may be committed only when its recorded terms
explicitly permit repository redistribution. Local-index-only downloads,
extracted text, chunks, and embeddings remain ignored and uncommitted.
Third-party figures, tables, images, and excerpts require their own permission
and are excluded unless separately approved.

## Retrieval Boundary

- Retrieval queries contain a deidentified clinical concept question only.
  Patient identifiers, patient summaries, raw FHIR, prompts, and provider
  objects are not fields in the retrieval request.
- Query text, result count, chunk text, excerpts, topics, and metadata are
  bounded by application-owned contracts.
- Results contain only approved, current documents and normalize provider data
  into application-owned chunks and citations.
- Raw queries and chunk bodies are not written to workflow audit records.
  Audits may record document/chunk IDs, result count, policy version, and a
  query fingerprint.

## Evidence Decisions

| Condition | Result | Workflow behavior when integrated in Phase 3.6 |
|---|---|---|
| Relevant current evidence with valid citations | `sufficient` | Generation may continue using only the returned citations |
| No results, stale-only results, or weak evidence | `insufficient` | Do not make a guideline-backed claim; route to review with a stable reason |
| Materially inconsistent approved sources | `conflicting` | Do not select a source silently; route to human review |
| Timeout or unavailable retrieval dependency | Typed capability failure | Fail safely with a stable code; do not generate an uncited answer |
| Malformed or provider-specific result | Typed response failure | Reject the result and fail safely |

`insufficient` is a valid evidence result, not an infrastructure exception.
Thresholds and scoring are deferred to sub-phase 3.5 and must not be inferred
from vector-store-specific fields.

## Review Gate

Sub-phase 3.2 may start only after this policy and its application-owned
contracts are accepted. Document acquisition then requires an individual
provenance and permission record; the publisher allowlist alone is
insufficient.
