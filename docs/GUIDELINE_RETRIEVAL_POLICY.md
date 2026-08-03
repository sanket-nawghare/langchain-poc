# Guideline Retrieval Policy

This policy governs Phase 3.5 retrieval from the local reviewed guideline
index. Retrieval is an educational evidence-selection mechanism, not a
clinical recommendation system.

## Trust Ownership

- The committed `data/guidelines/corpus-lock.json` is the authority for source
  title, publisher, canonical URL, publication/version metadata, license
  review, lifecycle, permissions, checksum, language, and supported topics.
- Weaviate is an untrusted candidate index. Its source metadata must match the
  trusted catalog but cannot create or modify a `GuidelineSource` or
  `Citation`.
- Weaviate may return only a normalized application-owned candidate containing
  stable object/chunk identity, bounded chunk text and lineage, stored source
  checksum/version metadata, embedding identity, and cosine distance.
- Citation identity is constructed by application code from the trusted source
  and validated chunk. A model never supplies or edits citation fields.

## Query Boundary

- A retrieval request contains only a bounded deidentified clinical query,
  optional allowlisted publishers, an as-of date, and `top_k` from one through
  eight.
- Patient identifiers, patient summaries, raw FHIR resources, prompts, model
  messages, and provider objects are rejected by the contracts.
- The query is embedded through the same versioned application capability used
  during indexing. Search requests carry exact parser and embedding model IDs,
  dimension, finite nonzero vector, eligible document IDs, and candidate limit.
- The query fingerprint is SHA-256 over the application-normalized query and is
  the only query-derived value eligible for audit persistence.

## Eligibility and Filtering

Before querying Weaviate, application code derives eligible documents from the
trusted catalog. A source is eligible only when all of these are true:

1. its exact use permission and current lifecycle allow indexing;
2. its publication date does not follow the request `as_of` date;
3. its publisher is included when an optional publisher filter is present;
4. its document ID and checksum belong to the current locked corpus.

The vector query then filters the fixed collection by schema version, parser
version, embedding model, current lifecycle, and the eligible document IDs. Returned
source checksum, publisher, version, and publication date must agree with the
trusted catalog or the entire response is malformed.

## Candidate and Result Bounds

- The candidate query is limited to at most 32 objects and the normalized
  result to the requested `top_k` of at most eight.
- Candidate chunk text remains limited to 3,000 characters; citation excerpts
  are application-derived and limited to 500 characters.
- Duplicate object IDs or chunk IDs, missing distance, non-finite or out-of-range
  distance, unknown fields, invalid chunk lineage, and metadata drift reject
  the response rather than being silently skipped.
- Candidates are re-ranked in application code. Final ordering uses the frozen
  Phase 3.5 relevance score, then vector similarity, then stable chunk ID so
  provider ordering never breaks a tie.

## Evidence Decisions

- No eligible source or no candidate is a valid `insufficient` result.
- Weak candidates below the calibrated Phase 3.5 threshold produce
  `insufficient`; they are not returned as supporting matches.
- Relevant candidates with trusted source/chunk/citation lineage produce
  `sufficient`.
- `conflicting` requires an explicit deterministic conflict signal between at
  least two approved sources. Similarity or differing wording alone must not be
  labeled a conflict. The starter corpus has no approved conflict fixture, so
  it must not infer one.
- Thresholds and the exact scoring formula are frozen only after the committed
  relevance fixtures are evaluated in checkpoint 3.5.3. They are application
  policy, never raw provider certainty.

## Failures

| Condition | Outcome |
|---|---|
| No eligible/current source, no candidates, or weak evidence | Valid `insufficient` result |
| Bounded query timeout | `GuidelineRetrievalTimeoutError` |
| Weaviate or embedding dependency unavailable | `GuidelineRetrievalUnavailableError` |
| Schema mismatch, malformed vector, provider field, metadata drift, or invalid lineage | `GuidelineRetrievalResponseError` |

Failures expose stable application messages and do not include raw queries,
chunk bodies, provider payloads, connection details, or credentials.
