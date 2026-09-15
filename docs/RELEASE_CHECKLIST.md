# MVP Release Checklist

Use this checklist before tagging the first MVP release.

## Local Setup

- `make setup` completes from a clean checkout.
- `make infra-up` starts PostgreSQL, HAPI FHIR, and Weaviate.
- `make fhir-seed` loads the locked synthetic cohort.
- `make guidelines-fetch` retrieves the reviewed WHO documents or confirms they
  are already present.
- `make guidelines-index` builds the local Weaviate guideline index.
- `make dev` starts the backend and frontend on loopback.

## Quality Gates

- `make check` passes.
- `make phase6-quality-gate` passes.
- `make fhir-verify` passes.
- `make guidelines-index-verify` passes.
- `make phase3-retrieval-live-gate` passes when infrastructure is running.
- `make phase3-live-gate` passes when backend, HAPI, and Weaviate are running.
- `make phase4-generation-live-gate` passes only when intentionally testing a
  configured live model provider.

## Demo Verification

- The frontend opens at `http://localhost:5173`.
- The backend health badge shows available.
- Allergy-summary questions complete without LLM use.
- Guideline questions return citations and an educational disclaimer.
- Medication-change questions demonstrate conservative review routing.
- Review queue behavior is understood: pre-generation reviews cannot be
  approved because no draft exists.
- History and graph views show workflow progress, transitions, and audit
  events without exposing raw patient payloads.

## Release Hygiene

- `docs/CURRENT_SYSTEM_CAPABILITIES.md` matches the actual demo scope.
- `docs/CURRENT_SYSTEM_DEMO_GUIDE.md` includes working patient IDs or explains
  how to read them from the synthetic cohort manifest.
- `README.md` links to setup, architecture, configuration, demo, extension,
  quality, and safety docs.
- `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md` are
  present.
- No real patient data, provider keys, generated FHIR bundles, downloaded PDFs,
  local SQLite files, or vector-store data are committed.
- Release notes summarize known limitations and non-medical-device boundaries.
