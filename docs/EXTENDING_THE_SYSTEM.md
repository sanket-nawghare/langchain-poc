# Extending the System

This guide describes the current extension points for the synthetic clinical
workflow MVP. Keep new behavior narrow, testable, redacted, and explicitly
documented in `docs/PROJECT_ROADMAP.md`.

## Add a Tool

1. Define a small protocol in `backend/app/tools/`.
2. Keep provider SDK objects and raw payloads behind an adapter in
   `backend/app/services/`.
3. Return application-owned domain models from `backend/app/domain/`.
4. Raise typed safe errors from the tool boundary; do not leak provider
   messages into workflow state or API responses.
5. Inject the tool through `WorkflowRuntime` if the graph needs it.
6. Add unit tests for success, timeout/unavailable behavior, malformed output,
   and redaction.

## Add a LangGraph Node

1. Add a node-name constant in `backend/app/workflow/graph.py`.
2. Implement a node function that accepts `WorkflowGraphState` and
   `Runtime[WorkflowRuntime]`.
3. Revalidate all tool results before placing them into workflow state.
4. Append an audit event with stable metadata only.
5. Add status transitions only when the workflow lifecycle changes.
6. Register the node and route in `build_workflow_graph()`.
7. Update frontend graph metadata if the node should be visible in the UI.
8. Add workflow graph tests for the happy path, failure path, streaming events,
   and redaction.

## Add a Model Provider

1. Implement `ResponseGenerator` in `backend/app/services/`.
2. Accept only `GroundedGenerationRequest`.
3. Return only `ResponseGenerationResult` with a strict `ResponseDraft`.
4. Do not allow the provider to create citations, disclaimers, safety policy,
   workflow status, or review decisions.
5. Map authentication, rate-limit, timeout, unavailable, context-limit,
   refusal, request, and malformed-output failures to safe typed errors.
6. Add settings to `backend/app/core/config.py` and `backend/.env.example`.
7. Wire provider selection in `create_configured_response_generator()`.
8. Add adapter tests without live provider calls.
9. Document provider setup and limitations in `docs/DEVELOPMENT.md` and
   `docs/CURRENT_SYSTEM_CAPABILITIES.md`.

## Add a Guideline

1. Confirm publisher, version, publication date, source URL, and local indexing
   permission.
2. Add metadata only to `data/guidelines/corpus-lock.json`.
3. Keep the downloaded document under ignored local guideline storage.
4. Run:

```bash
make guidelines-fetch
make guidelines-verify
make guidelines-chunk
make guidelines-index
make phase3-retrieval-live-gate
```

5. Add retrieval evaluation cases for expected sufficient and insufficient
   queries.
6. Update the current knowledge boundary docs before using the new guideline
   in a demo.

## Redaction Checklist

- No raw FHIR payloads in workflow snapshots.
- No patient ID, display name, query text, full prompts, provider payloads, or
  provider exception details in API responses.
- No real patient data in fixtures, logs, screenshots, or docs.
- No API keys in committed files.
- Citations must come from application-owned retrieved evidence, not model text.
