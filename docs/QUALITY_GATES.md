# Quality Gates

Every implementation sub-phase must finish with:

```bash
make check
```

This command checks backend formatting, linting, static types, and tests;
frontend formatting, linting, static types, tests, and production build; and
the Docker Compose configuration. It does not require HAPI FHIR, PostgreSQL, or
Weaviate to be running.

## Focused Commands

Use the smaller targets while developing:

| Area | Commands |
|---|---|
| Backend | `make backend-format`, `make backend-check` |
| Frontend | `make frontend-format`, `make frontend-check` |
| Tests only | `make test` |
| Compose | `make infra-config` |
| Seeded Phase 2 API | `make phase2-live-gate` |
| Guideline index | `make guidelines-index`, `make guidelines-index-verify` |
| Everything | `make check` |

`backend-check` runs Ruff formatting and linting, mypy strict type checking,
and pytest. `frontend-check` runs Prettier, ESLint, TypeScript, and Vitest.

`phase2-live-gate` is deliberately opt-in because it requires healthy local
infrastructure, the checksum-locked synthetic cohort loaded in HAPI, and a
running backend. It verifies the cohort before exercising completed, review,
rejected, missing-patient, invalid-input, persistence, and redaction paths.

The guideline index targets are also opt-in because they require the ignored
reviewed PDFs and a healthy loopback-only Weaviate instance. Ingestion verifies
the committed corpus and chunk locks before embedding or mutation. A repeated
run must report every unchanged object as skipped.

## Pre-commit

After `make setup`, install the local hooks once:

```bash
make pre-commit-install
```

Run every hook manually with:

```bash
make pre-commit
```

The hooks run fast formatting and lint checks for changed backend and frontend
files and validate Compose when its configuration changes. Tests and builds
remain in `make check` and CI.

## Continuous Integration

The `Quality` GitHub Actions workflow runs independent backend, frontend, and
Compose jobs. Backend and frontend dependencies are installed from committed
lockfiles. CI caches only downloaded dependency artifacts keyed by those
lockfiles; it does not cache `.env` files, application databases, synthetic
patient data, build output, or secrets.

Before pausing for any sub-phase review:

1. Run the focused checks during implementation.
2. Run `make check`.
3. Record the result in the active phase document.
4. Commit implementation, tests, lockfiles, and documentation together.
