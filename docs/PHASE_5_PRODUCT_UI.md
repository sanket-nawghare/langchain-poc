# Phase 5 - Product UI and Workflow Visualization Plan

This plan turns the backend workflow into a usable browser experience while
keeping synthetic-only and redaction boundaries visible. Each checkpoint should
be independently reviewable and end with focused frontend tests plus
`make check`.

## Objectives

- Let a user submit a synthetic patient workflow without using curl.
- Make workflow status, citations, safety routing, and review actions
  understandable from the UI.
- Keep raw patient data, full prompts, provider payloads, and hidden workflow
  state out of the browser.
- Support reviewer approval, rejection, and request-changes actions with
  version-aware feedback.
- Add enough visualization and history for the workflow to be inspectable
  without reading server logs.

## Tracking

| Sub-phase | Deliverable | Status |
|---|---|---|
| 5.1 UI shell and API contracts | Typed frontend API client, request form, and safe result rendering skeleton | `[x]` |
| 5.2 Workflow run experience | Loading, success, pending-review, rejected, failed, and empty states for workflow submission | `[x]` |
| 5.3 Review queue and actions | Reviewer queue/detail/actions with safety reasons and stale-action handling | `[x]` |
| 5.4 Workflow visualization and history | Graph/status visualization, run history, transitions, and audit details | `[ ]` |
| 5.5 Phase 5 integration gate | Accessibility, redaction, critical journeys, and documentation pass | `[ ]` |

## Sub-phase 5.1 - UI Shell and API Contracts

- `[x]` Add typed frontend contracts for workflow snapshots, citations,
  evidence, safety results, review items, and API envelopes.
- `[x]` Add a small API client for health, create workflow, inspect workflow,
  list reviews, inspect review, and record review action.
- `[x]` Replace the placeholder with a work-focused app shell and a workflow
  request form for synthetic patient ID plus clinical question.
- `[x]` Render a safe first-pass workflow result without exposing raw patient
  context or hidden request data.

The placeholder screen has been replaced with a compact operational shell for
submitting synthetic clinical-QA workflow runs. Frontend API contracts now cover
workflow snapshots, citations, guideline evidence, safety results, review queue
items, and review actions. The first result panel renders completed,
pending-review, rejected, and failed snapshots with status metadata, draft/final
answer content when present, safety reason summaries, citations, and safe error
messages.

## Sub-phase 5.2 - Workflow Run Experience

- `[x]` Add ergonomic loading, retry, success, pending-review, rejected, failed,
  and validation states.
- `[x]` Render final responses with application-owned citations and disclaimer.
- `[x]` Render pending-review and rejected states with safety reason summaries.
- `[x]` Add component tests for the major workflow states.

The workflow run surface now includes a fuller status summary, safe API error
messaging, sample-question shortcut, final and pending-review answer panels,
safety reasons, citations, transitions, redacted audit summaries, and a local
recent-run history. Component coverage exercises available/unavailable backend
status, completed runs, pending-review runs, API validation failures, and local
history.

## Sub-phase 5.3 - Review Queue and Actions

- `[x]` Add pending-review list and detail views.
- `[x]` Show draft answer, citations, safety reasons, review version, and safe
  workflow metadata.
- `[x]` Add approve, reject, and request-changes actions with reviewer identity
  and rationale.
- `[x]` Handle stale, duplicate, invalid, non-pending, and storage-failure
  responses safely.

The Review tab can refresh pending items, select a review, inspect draft answer,
citations, evidence status, safety reasons, and review version, then submit
approve, reject, or request-changes actions with reviewer identity and
rationale. Successful actions update the selected workflow result and local
history; stale or failed review actions surface safe API error codes without
exposing hidden state.

## Sub-phase 5.4 - Workflow Visualization and History

- `[ ]` Visualize graph nodes and current workflow status.
- `[ ]` Add run history and selected-run inspection.
- `[ ]` Show transitions and redacted audit details without prompt, patient, or
  provider body leakage.
- `[ ]` Add keyboard-friendly navigation between request, review, history, and
  detail surfaces.

## Sub-phase 5.5 - Phase Gate and Documentation

- `[ ]` Run frontend and full-project checks.
- `[ ]` Verify critical user and reviewer journeys with automated tests.
- `[ ]` Verify browser-visible payloads do not include raw patient context,
  full prompts, provider payloads, or secrets.
- `[ ]` Update roadmap and stop for final Phase 5 review.

## Phase Exit Criteria

- `[ ]` A user can complete the MVP workflow entirely through the UI.
- `[ ]` A reviewer can act on a pending run and see it resume.
- `[ ]` Workflow status is understandable without reading server logs.
- `[ ]` Critical UI journeys pass automated tests.
