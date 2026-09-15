# Phase 6 - Quality, Security, and Observability

Phase 6 makes the local MVP easier to operate, debug, and demo without changing
the clinical scope. The system is still an educational synthetic-data workflow,
not a medical device.

## Current Observability

- Every HTTP response includes an `X-Request-ID` header.
- The API emits structured JSON request logs through the
  `clinical_workflow.http` logger.
- `GET /health/metrics` exposes process-local metrics:
  - total request count;
  - status-class counts;
  - route counts;
  - average and maximum latency;
  - request-body rejection count;
  - workflow rate-limit count.
- Workflow snapshots already expose durable workflow IDs, correlation IDs,
  trace IDs, transitions, safe audit events, retrieved evidence metadata, safety
  decisions, and provider generation telemetry when a provider reports it.
- Provider generation telemetry currently includes model alias, latency, input
  tokens, and output tokens when available. Estimated cost is intentionally not
  calculated until a reviewed pricing table or billing integration is added.
- LangSmith tracing is default-off. Set
  `CLINICAL_LANGSMITH_TRACING_ENABLED=true` only for explicit local/debug runs
  where exporting workflow inputs and state to LangSmith is acceptable.

## Security Defaults

- Request validation errors do not echo user input, patient IDs, FHIR payloads,
  provider errors, or secret values.
- Workflow requests are capped by `CLINICAL_MAX_REQUEST_BODY_BYTES`.
- Workflow creation is rate-limited per client by
  `CLINICAL_WORKFLOW_RATE_LIMIT_PER_MINUTE`.
- Responses include conservative browser hardening headers:
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and `Content-Security-Policy`.
- OpenAI and Anthropic providers require HTTPS endpoints and an API key.
- Ollama is restricted to loopback hosts.
- Real FHIR resources, patient display names, raw guideline documents, and full
  model prompts remain outside durable workflow API responses.

## Quality Gates

Run the offline Phase 6 gate:

```bash
make phase6-quality-gate
```

Run the full repository gate:

```bash
make check
```

The Phase 6 gate checks:

- backend and frontend lockfiles are present;
- common committed secret patterns are absent;
- the operator-facing Phase 6 and capability docs are present.

The backend suite includes:

- golden workflow outcome checks for guideline-only completion and medication
  review routing;
- prompt-injection coverage for malicious guideline text treated as data;
- dependency-failure tests for guideline retrieval and response generation;
- HTTP security header, request-body limit, rate-limit, and metrics coverage;
- local Ollama structured-output recovery for common JSON wrappers.

## Common Failure Runbook

`response_generation_rate_limited`

- Provider rejected generation due to quota/rate limits.
- For demo stability, use `CLINICAL_LLM_PROVIDER=fake` or local Ollama.
- If using OpenAI or Anthropic, wait and retry with a smaller model or lower
  frequency.

`response_generation_timeout`

- Provider did not return within `CLINICAL_LLM_REQUEST_TIMEOUT_SECONDS`.
- Local models can be slow; increase the timeout up to the configured maximum or
  use a smaller Ollama model.

`response_generation_invalid_output`

- Provider returned text that could not become a strict `ResponseDraft`.
- Ollama now accepts valid answer JSON inside common wrappers, but still rejects
  empty, oversized, or non-answer payloads.

`guideline_retrieval_unavailable`

- Weaviate or the local guideline index is unavailable.
- Check `docker compose ps`, then run `make guidelines-index-verify`.

`fhir_unavailable` or `patient_not_found`

- HAPI FHIR is down or the selected synthetic patient is not loaded.
- Check `docker compose ps`, then run `make fhir-verify`.

`request_body_too_large`

- The request exceeded `CLINICAL_MAX_REQUEST_BODY_BYTES`.
- Keep demo prompts short; this workflow is designed for bounded clinical
  questions, not document upload.

`rate_limited`

- Too many workflow submissions were received from the same client in one
  minute.
- Wait for the retry window or raise
  `CLINICAL_WORKFLOW_RATE_LIMIT_PER_MINUTE` for local stress testing.

## Data Retention and Recovery

- Durable workflow state is stored in the configured SQLite database.
- Stored workflow snapshots are redacted projections; they retain IDs, status,
  evidence metadata, citations, safe audit details, review records, and final
  answers.
- Raw FHIR payloads, raw guideline documents, complete prompts, provider API
  keys, and patient display names are not stored in workflow snapshots.
- On API startup, interrupted queued/running workflows are marked failed with
  `workflow_interrupted`; work is not replayed automatically.
- Local reset commands remain explicit and confirmation-gated in the Makefile.

## Database Notes

- The MVP currently uses SQLite for workflow checkpoints.
- There are no schema migrations yet; schema initialization is owned by
  `SqliteWorkflowRunStore.initialize()`.
- Backup for local demos is file-based: stop the API and copy the configured
  SQLite database plus `-wal`/`-shm` files when present.
- Before recovery demos, run `/health/ready` and inspect `/health/metrics` to
  confirm the process is serving and dependencies are reachable.
