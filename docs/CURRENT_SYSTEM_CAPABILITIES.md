# Current System Capabilities

## Executive Summary

The AI Clinical Workflow Engine is a **synthetic-data clinical workflow
prototype**. Its primary value is demonstrating how patient context, reviewed
guideline retrieval, bounded LLM generation, deterministic safety checks,
human review, citations, and audit history can be coordinated through one
observable LangGraph workflow.

It is not a general medical expert, diagnostic system, prescribing tool, or
medical device. It must not be used with real patient data or for real clinical
decisions.

## What the System Can Be Used For

The current implementation is useful for:

- demonstrating read-only access to synthetic FHIR patient records;
- showing a deterministic patient allergy-summary workflow;
- answering a narrow set of questions from a reviewed local WHO guideline
  corpus;
- demonstrating retrieval-augmented generation with application-owned
  citations;
- comparing deterministic, cloud, and local LLM response providers;
- showing safety routing before and after model generation;
- demonstrating a limited human-review queue for generated drafts;
- inspecting workflow nodes, state transitions, safety outcomes, citations,
  failures, and audit events in a browser;
- testing provider failures such as timeouts, rate limits, malformed output,
  context limits, and unavailable services; and
- serving as a reference architecture for provider-neutral clinical workflow
  orchestration.

## Implemented End-to-End Paths

### 1. Direct Synthetic Patient Allergy Summary

Supported examples:

```text
What is the allergy history of this patient?
What are the current allergies for this patient?
List the known allergies for this patient.
Give me the patient's allergy summary.
```

The system:

1. validates the request;
2. classifies it as clinical QA;
3. reads the synthetic patient from HAPI FHIR;
4. normalizes the patient's `AllergyIntolerance` records;
5. runs the deterministic safety pre-check; and
6. constructs a final allergy summary with a local patient-evidence citation.

This path intentionally does not use Weaviate or an LLM. In the UI graph it
ends at **Patient facts**, which represents the
`finalize_patient_summary` node. Ending there with a `completed` status is a
successful result, not a stopped workflow.

### 2. Reviewed Guideline Question Answering

Strong currently supported examples:

```text
What blood pressure target is recommended for adults?
When is pharmacological treatment for hypertension recommended?
What diagnostic criteria are used for type 2 diabetes?
How should glycaemic control be monitored in type 2 diabetes?
```

The system:

1. validates and classifies the question;
2. retrieves and normalizes the synthetic patient context;
3. searches reviewed guideline chunks in Weaviate;
4. determines whether the evidence is sufficient;
5. applies deterministic pre-generation safety rules;
6. selects bounded, deidentified patient facts and evidence excerpts;
7. asks the configured response generator for a strict answer draft;
8. validates the structured model output;
9. applies post-generation safety rules; and
10. attaches application-owned citations and an educational disclaimer before
    finalization.

The browser requests a server-sent event stream and updates the execution graph
when each LangGraph node starts and completes. Local CPU inference through
Ollama can still take considerably longer than a cloud model, but the Draft
node remains visibly active while generation is running.

### 3. Safety and Human Review Demonstration

Example:

```text
Should this patient start hypertension medication?
```

Medication-change language is conservatively detected before generation. The
workflow enters `pending_review` without creating a draft.

There are currently two distinct review states:

| Review state | Draft exists | Available behavior |
|---|---:|---|
| Pre-generation review | No | Reject or request changes; Approve is disabled |
| Post-generation review | Yes, with citations | Approve can publish the existing draft; Reject or request changes terminates it |

Important current limitation: reviewer rationale is audit text, not an
instruction to LangGraph. Entering `continue` does not resume generation.
Pre-generation reviews cannot currently be authorized to continue, and
**Request changes** records the action and terminates the run rather than
regenerating a draft.

## Patient Context Capabilities

The read-only HAPI FHIR adapter currently retrieves and normalizes:

- conditions;
- allergies;
- medications;
- encounters;
- observations;
- procedures; and
- diagnostic reports and laboratory-related records.

The normalized context supports safety checks and grounded generation. Before
an LLM call, the application selects at most 32 relevant facts and removes the
patient ID, display name, and raw FHIR payload.

Only allergies currently have a dedicated direct-answer route. Although other
record categories are retrieved, standalone requests such as “list this
patient's medications” or “show active conditions” are not implemented as
direct patient-summary answers and may fall through to guideline retrieval.

## Guideline Knowledge Boundary

The reviewed local corpus currently contains:

1. WHO, *Guideline for the pharmacological treatment of hypertension in
   adults* (2021).
2. WHO, *Diagnosis and management of type 2 diabetes (HEARTS-D)* (2020).

Weaviate stores the reviewed document chunks and vectors. Retrieval applies
source eligibility rules, relevance thresholds, stable document/chunk
identities, and evidence assessment. Only sufficient evidence can reach model
generation. Missing, weak, or conflicting evidence is not converted into an
uncited answer.

The system should not be presented as knowledgeable about clinical topics
outside these documents.

## Response Generation Providers

The response-generation interface is provider-neutral and currently supports:

| Provider | Configuration value | Intended use |
|---|---|---|
| Deterministic fake | `fake` | Credential-free tests and predictable workflow demonstrations |
| OpenAI | `openai` | Cloud grounded generation through the Responses API |
| Anthropic | `anthropic` | Cloud grounded generation through the Messages API |
| Ollama | `ollama` | Credential-free local generation through `/api/chat` |

Ollama defaults to `qwen3:4b`, structured JSON output, an 8,192-token context
window, and a loopback-only server address. Local generation is CPU-bound on a
machine without a supported GPU. The configured timeout is bounded, and Ollama
requests are not automatically retried because cancelled CPU inference may
continue occupying the local server.

Regardless of provider:

- the model receives only bounded deidentified facts and evidence excerpts;
- retrieved citation identities remain application-owned;
- the model cannot add or replace citations or the disclaimer;
- unknown or oversized structured fields are rejected;
- provider errors become stable redacted workflow failure codes; and
- provider output never silently falls back to an uncited clinical answer.

## Safety Capabilities

The deterministic pre-generation policy currently checks for:

- urgent language;
- requests to autonomously start, stop, change, or adjust medication;
- apparent medication/allergy conflicts;
- missing core patient context; and
- truncated patient context.

The post-generation policy checks for:

- autonomous medication-change language in the draft;
- diagnosis or prescribing language; and
- missing evidence-grounding language.

Safety outcomes are `pass`, `review`, or `block`, with a policy version,
severity, stable reason code, and evidence references. These rules are
conservative demonstrations, not validated clinical decision rules.

## Workflow and Audit Capabilities

LangGraph coordinates explicit nodes for:

- execution start;
- intent classification;
- patient retrieval;
- guideline retrieval;
- safety pre-check;
- direct patient-summary finalization;
- grounded draft generation;
- draft safety evaluation; and
- final response qualification.

Workflow snapshots are stored in local SQLite and include:

- workflow, correlation, and trace IDs;
- status and timestamps;
- evidence assessment and citation projections;
- safety results;
- generated draft or final response when present;
- transitions;
- review version and reviewer action; and
- redacted audit events.

Pending reviews survive backend restarts. Individual workflows can be fetched
by ID. The frontend's general run-history list is browser-session state and is
not currently a complete persisted-history browser.

## User Interface Capabilities

The React interface currently provides:

- synthetic patient ID and question submission;
- backend availability status;
- workflow status and failure display;
- generated answer, disclaimer, evidence excerpts, and citations;
- a React Flow execution-path visualization;
- transitions and audit-event summaries;
- a pending-review queue;
- reviewer ID, rationale, approve, reject, and request-changes controls; and
- local in-browser run history.

The execution graph shows the last executed or terminal node; an orange node
does not by itself mean failure. The workflow status and failure code determine
the actual outcome.

## API Capabilities

The primary HTTP endpoints are:

| Endpoint | Purpose |
|---|---|
| `GET /health/live` | Backend process health |
| `GET /health/ready` | SQLite, HAPI FHIR, and Weaviate readiness |
| `GET /api/v1/patients/{patient_id}/summary` | Normalized synthetic patient summary |
| `POST /api/v1/workflows` | Execute one workflow; stream node events when `Accept: text/event-stream` is sent, otherwise return the final JSON snapshot |
| `GET /api/v1/workflows/{workflow_id}` | Read one persisted workflow snapshot |
| `GET /api/v1/workflows/reviews` | List pending reviews |
| `GET /api/v1/workflows/{workflow_id}/review` | Read one pending review projection |
| `POST /api/v1/workflows/{workflow_id}/review-actions` | Record an attributable review action |
| `GET /api/v1/evidence/synthetic-patient-summary` | Explain the local patient-summary citation |

FHIR access is read-only. The application does not create prescriptions,
change medication, schedule appointments, or write clinical data back to HAPI
FHIR.

## Infrastructure and Storage

The local system uses:

- FastAPI for the backend API;
- LangGraph for workflow orchestration;
- React, Vite, and React Flow for the UI;
- HAPI FHIR with PostgreSQL for synthetic clinical records;
- Weaviate for guideline-vector storage and retrieval;
- SQLite for application workflow snapshots and audit state; and
- Ollama or an optional cloud provider for grounded generation.

The project includes repeatable synthetic-data import, guideline acquisition,
parsing, indexing, verification, retrieval evaluation, and quality-check
commands. Synthetic clinical payloads and downloaded guideline artifacts are
kept out of source control where required by project policy.

## Current Limitations

The system currently cannot reliably:

- diagnose a patient;
- prescribe, select, start, stop, or dose medication;
- produce a patient-specific treatment plan;
- calculate validated patient risk scores;
- answer broad medical questions outside the two-document corpus;
- directly answer standalone condition, medication, observation, procedure, or
  encounter-summary questions;
- authorize and resume a workflow stopped by a pre-generation review;
- regenerate a draft after **Request changes**;
- stream model tokens inside the active Draft node (node-level progress is
  streamed, but provider token output remains buffered and strictly parsed);
- browse all persisted workflow history after a browser refresh;
- write to FHIR or external clinical systems;
- enforce production authentication, authorization, tenancy, or operational
  governance; or
- safely process real patient information.

Phases 6 and 7 of the roadmap—quality/observability hardening and release
packaging—are not yet complete.

## Interpreting Outcomes

| Outcome | Meaning |
|---|---|
| `completed` | A direct patient summary or cited guideline answer finalized successfully |
| `pending_review` with a draft | A generated draft requires human review and may be approved |
| `pending_review` without a draft | Retrieval or pre-generation safety stopped generation; Approve is unavailable |
| `rejected` | The request was unsupported, blocked, or terminated by reviewer action |
| `failed` | A dependency, timeout, provider, or contract failed safely; inspect `failure_code` |

## Recommended Positioning

Use this concise description in a demonstration:

> This is a synthetic-data clinical workflow prototype that demonstrates
> read-only FHIR context, reviewed guideline retrieval, bounded local or cloud
> generation, deterministic safety controls, citations, human review, and an
> auditable LangGraph execution path. Its current clinical scope is direct
> allergy summaries plus selected adult hypertension and type 2 diabetes
> guideline questions.

For tested demo questions and expected outcomes, see the
[Current System Demo Guide](CURRENT_SYSTEM_DEMO_GUIDE.md). For planned work,
see the [Project Roadmap](PROJECT_ROADMAP.md).
