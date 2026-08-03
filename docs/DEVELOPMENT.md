# Local Development Guide

## Prerequisites

Install:

- Python 3, used only to bootstrap the project-local `uv`.
- Node.js 24.
- pnpm 10.28.2.
- Docker with the Compose plugin.
- GNU Make.

The repository then manages Python 3.12, backend packages, and frontend
packages from committed lockfiles. No model API key is required for Phase 0.

## First Setup

From the repository root:

```bash
make setup
make infra-up
make check
```

`make setup` creates ignored local tooling and dependency directories.
`make infra-up` starts PostgreSQL, HAPI FHIR, and Weaviate and waits for their
health checks. `make check` verifies both applications and the Compose
configuration.

Environment files are optional because safe local defaults are built in. For
local overrides:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Both copied files are ignored. Never commit credentials or real patient data.

## Start the Applications

Start both development servers:

```bash
make dev
```

Or run them in separate terminals:

```bash
make backend-dev
make frontend-dev
```

If either development port is occupied, select another loopback port:

```bash
BACKEND_PORT=18000 make backend-dev
FRONTEND_PORT=15173 make frontend-dev
```

When changing the backend port, set the matching `VITE_API_BASE_URL` in
`frontend/.env`.

Default endpoints:

| Component | Address |
|---|---|
| Frontend | `http://localhost:5173` |
| Backend liveness | `http://localhost:8000/health/live` |
| Backend readiness | `http://localhost:8000/health/ready` |
| Synthetic patient summary | `http://localhost:8000/api/v1/patients/{patient_id}/summary` |
| Create workflow run | `POST http://localhost:8000/api/v1/workflows` |
| Inspect workflow run | `GET http://localhost:8000/api/v1/workflows/{workflow_id}` |
| Backend OpenAPI | `http://localhost:8000/docs` |
| HAPI FHIR | `http://localhost:8080/fhir` |
| HAPI PostgreSQL | `127.0.0.1:5434` |
| Weaviate HTTP | `http://localhost:8081` |
| Weaviate gRPC | `127.0.0.1:50051` |

Verify the API:

```bash
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
```

Liveness reports whether FastAPI can serve a request. Readiness checks SQLite,
HAPI FHIR, and Weaviate. It returns HTTP 200 only when all dependencies are
available and HTTP 503 otherwise.

After `make fhir-seed`, query one locked synthetic patient through the
application API:

```bash
PATIENT_ID=$(jq -r '.fixtures[0].patient_id' \
  data/synthetic/cohort-manifest.json)
curl --fail \
  "http://localhost:8000/api/v1/patients/${PATIENT_ID}/summary"
```

The route returns an `ApiSuccess[PatientSummary]` envelope. It exposes only
bounded normalized fields and lists any incomplete bounded collections in
`truncated_categories`. Invalid IDs return HTTP 400, missing synthetic patients
404, malformed upstream responses 502, and HAPI timeout or unavailability 503.
Error bodies use the safe `ApiError` envelope and never include upstream
payloads or exception details. This unauthenticated endpoint is for the
loopback-only synthetic development environment, not real patient data or
production deployment.

Create a synchronous workflow run for the same seeded patient:

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "{\"patient_id\":\"${PATIENT_ID}\",\"query\":\"What precautions relate to this patient's conditions?\"}" \
  http://localhost:8000/api/v1/workflows
```

The response includes distinct request, workflow, correlation, and trace IDs
plus the final redacted status snapshot. It does not return or persist the
query, patient ID/context, prompts, or provider payloads. Copy
`data.workflow_id` from that response to inspect the persisted checkpoint:

```bash
curl --fail \
  "http://localhost:8000/api/v1/workflows/${WORKFLOW_ID}"
```

Run creation is synchronous in Phase 2.5. If the process stops after storing an
incomplete checkpoint, the next application startup marks it failed with
`workflow_interrupted`; it does not automatically replay clinical work.

With infrastructure seeded and the backend running, execute the complete
opt-in Phase 2 gate:

```bash
make phase2-live-gate
```

The target verifies the locked HAPI cohort, then exercises the reviewed
`sparse-control-01` happy path, safety review, unsupported intent, missing
patient, invalid request, persistence, and redaction. It uses no model API key
or network model call.

## Reviewed Guideline Corpus

Phase 3.2 selects two local-only WHO PDF artifacts for the synthetic metabolic
and cardiovascular scenarios. Their contents remain ignored; Git stores only
the reviewed provenance and checksum lock.

Acquire missing files from the exact approved WHO download URLs:

```bash
make guidelines-fetch
```

Verify existing files without downloading anything:

```bash
make guidelines-verify
```

See the [guideline input record](../data/guidelines/README.md) and
[source policy](GUIDELINE_SOURCE_POLICY.md) for the exact sources and use
restrictions. These commands do not parse, embed, or index the PDFs, and they
do not modify Weaviate.

## Configuration

Backend variables use the `CLINICAL_` prefix and are documented in
`backend/.env.example`. The frontend supports `VITE_API_BASE_URL`.

The read-only FHIR adapter supports these validated backend settings:

| Variable | Default | Bound |
|---|---:|---|
| `CLINICAL_FHIR_REQUEST_TIMEOUT_SECONDS` | `5` | Greater than 0, at most 30 |
| `CLINICAL_FHIR_MAX_RETRIES` | `2` | 0–3 |
| `CLINICAL_FHIR_RETRY_BACKOFF_SECONDS` | `0.1` | 0–5 |
| `CLINICAL_FHIR_MAX_PAGES_PER_SEARCH` | `5` | 1–20 |
| `CLINICAL_FHIR_MAX_RECORDS_PER_TYPE` | `500` | 1–500 |
| `CLINICAL_WORKFLOW_NODE_TIMEOUT_SECONDS` | `10` | Greater than 0, at most 30 |
| `CLINICAL_WORKFLOW_NODE_MAX_RETRIES` | `1` | 0–3 |

Compose supports these shell or root `.env` overrides:

| Variable | Default |
|---|---|
| `HAPI_FHIR_PORT` | `8080` |
| `HAPI_DB_PORT` | `5434` |
| `HAPI_DB_NAME` | `hapi` |
| `HAPI_DB_USER` | `hapi` |
| `HAPI_DB_PASSWORD` | `hapi-local-only` |
| `WEAVIATE_HTTP_PORT` | `8081` |
| `WEAVIATE_GRPC_PORT` | `50051` |

Published ports bind to loopback. The default database password and anonymous
Weaviate access are for isolated local development only.

## Quality and Tests

Run all required gates:

```bash
make check
```

Install the Git hook once and run it manually when needed:

```bash
make pre-commit-install
make pre-commit
```

See [Quality Gates](QUALITY_GATES.md) for focused commands and CI parity.

## Infrastructure Lifecycle

```bash
make infra-status
make infra-logs
make infra-down
```

`infra-down` keeps the named volumes. The following commands delete local data
and therefore require explicit confirmation:

```bash
make infra-reset CONFIRM=1
make app-data-reset CONFIRM=1
```

FHIR resources must be created through the HAPI FHIR API, never by inserting
into HAPI's PostgreSQL tables. Generate missing local synthetic files, seed the
locked cohort, and verify it with:

```bash
make fhir-seed
make fhir-verify
```

`fhir-seed` is idempotent for an empty or exactly matching local server. It
refuses unexpected or partial contents and asks for the guarded reset:

```bash
make fhir-reset CONFIRM=1
make fhir-seed
```

FHIR write and reset commands accept only explicit loopback `/fhir` URLs.
`fhir-reset` validates the target and exact Compose volume label, then replaces
only the HAPI PostgreSQL volume; Weaviate data is retained.

pgAdmin is inspection-only for the HAPI-managed schema. Do not insert, update,
delete, truncate, or migrate HAPI tables through pgAdmin or direct SQL.

## Troubleshooting

### `uv: not found`

Use the Makefile commands instead of calling `uv` directly:

```bash
make backend-sync
```

The Makefile bootstraps pinned `uv` into `.tooling/`.

### A dependency port is already in use

Override the conflicting Compose port for the current shell:

```bash
HAPI_DB_PORT=55434 make infra-up
```

Update matching application or pgAdmin settings when overriding a service
port.

For the application development servers, use `BACKEND_PORT` or
`FRONTEND_PORT` as shown in the startup section.

### Readiness returns HTTP 503

Check container state and recent logs:

```bash
make infra-status
docker compose logs --tail=100 hapi-db hapi-fhir weaviate
```

The readiness response identifies the unavailable dependency without exposing
its raw exception.

### HAPI takes longer to become healthy

The initial startup creates its PostgreSQL schema and can take longer than
later starts. `make infra-up` waits up to five minutes. Inspect
`docker compose logs hapi-fhir` if it exceeds that window.

### Frontend cannot reach the backend

Confirm `http://localhost:8000/health/live` works. If the backend uses a
different port, set `VITE_API_BASE_URL` in `frontend/.env` and restart Vite.

### Dependency installation reports a stale lockfile

Do not bypass frozen installs during normal setup. Reconcile intentional
dependency changes in `pyproject.toml` or `package.json`, regenerate the
corresponding lockfile, and commit both files together.

### Local state must be reset

Use the guarded reset targets above. Do not delete repository-wide directories
or Docker volumes manually. `fhir-reset` removes only HAPI FHIR data,
`infra-reset` removes HAPI and Weaviate data, and `app-data-reset` removes only
the local SQLite files.

## Development Constraints

- Use only synthetic data whose provenance is known.
- Do not log full FHIR resources, secrets, prompts with patient context, or raw
  retrieved documents.
- Do not add model credentials to committed files.
- Treat this software as an educational demonstration, not medical advice or a
  medical device.
- Keep implementation within the active roadmap phase and stop at its review
  checkpoint.
