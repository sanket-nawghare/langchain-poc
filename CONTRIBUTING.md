# Contributing

Thanks for improving this synthetic clinical workflow project. Contributions
should keep the MVP safe, reproducible, and honest about its limits.

## Ground Rules

- Use synthetic data only.
- Do not commit provider keys, real patient data, downloaded guideline PDFs,
  generated FHIR bundles, local databases, or vector-store data.
- Keep provider SDK objects behind service adapters.
- Preserve redaction boundaries in API responses, logs, tests, and docs.
- Update `docs/PROJECT_ROADMAP.md` and related docs when behavior changes.

## Local Workflow

```bash
make setup
make check
make phase6-quality-gate
```

When changing FHIR, guideline retrieval, or workflow behavior, also run the
matching live gates with local infrastructure.

## Pull Request Checklist

- Tests cover success, failure, empty, and redaction behavior for the changed
  boundary.
- `make check` passes.
- New settings are documented in `backend/.env.example` and
  `docs/DEVELOPMENT.md`.
- Public behavior is reflected in capability/demo docs.
- Important tradeoffs are recorded in the roadmap decision log.

## Clinical Safety

This repository is not a medical device and must not be used for real clinical
decisions. Do not add behavior that diagnoses, prescribes, writes to FHIR, or
claims broad medical expertise without a reviewed roadmap decision and safety
design.
