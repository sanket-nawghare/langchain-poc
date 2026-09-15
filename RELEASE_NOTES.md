# Release Notes

## MVP Candidate - 2026-09-15

This is the first documented MVP candidate for the AI Clinical Workflow Engine.

### Included

- FastAPI backend with typed domain contracts and safe error envelopes.
- React/Vite frontend for workflow request, review, history, and graph views.
- Local HAPI FHIR integration for read-only synthetic patient summaries.
- Deterministic Synthea cohort selection, seeding, and verification workflow.
- Local Weaviate guideline retrieval over reviewed WHO hypertension and type 2
  diabetes documents.
- Provider-neutral response generation with deterministic fake, OpenAI,
  Anthropic, and local Ollama adapters.
- Grounded generation with application-owned citations and disclaimer.
- Deterministic pre-generation and post-generation safety checks.
- Persisted workflow checkpoints, transitions, review records, and audit
  events.
- Server-sent workflow node progress events.
- Phase 6 observability and security guardrails.

### Known Limitations

- Synthetic-data demonstration only; not a medical device.
- Direct patient-data answers currently cover allergy history only.
- The reviewed guideline corpus is intentionally small.
- Pre-generation review can reject or request changes but cannot approve a run
  to continue because no draft exists yet.
- Local Ollama inference can be slow on CPU-only machines.
- Estimated cost is not calculated until a reviewed pricing source or billing
  integration is added.
- Authentication, authorization, SMART on FHIR, production deployment manifests,
  and role-based access control are future work.

### Verification

Before tagging, run:

```bash
make check
make phase6-quality-gate
```

For a full local demo with infrastructure, also run:

```bash
make fhir-verify
make guidelines-index-verify
make phase3-retrieval-live-gate
make phase3-live-gate
```
