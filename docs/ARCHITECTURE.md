# Current Architecture

## Current System

Phase 1 adds reproducible synthetic FHIR seeding, a bounded read-only HAPI
adapter, minimum-necessary normalization, and a normalized patient-summary API
to the Phase 0 application and infrastructure foundation. Guideline ingestion,
model calls, and LangGraph execution remain unimplemented.

```mermaid
flowchart LR
    Browser["Browser"]
    UI["React / Vite frontend"]
    API["FastAPI backend"]
    Summary["Patient summary service"]
    FHIRClient["Read-only FHIR interface"]
    Domain["Provider-neutral domain contracts"]
    SQLite[("SQLite application data")]
    HAPI["HAPI FHIR"]
    Postgres[("PostgreSQL")]
    Weaviate[("Weaviate")]

    Browser --> UI
    UI -->|"GET /health/live"| API
    API --> Domain
    API -->|"GET /api/v1/patients/{id}/summary"| Summary
    Summary --> FHIRClient --> HAPI
    Summary --> Domain
    API -->|"readiness probe"| SQLite
    API -->|"GET /fhir/metadata"| HAPI
    API -->|"ready probe"| Weaviate
    HAPI --> Postgres
```

All host-published service ports bind to `127.0.0.1`. HAPI FHIR and Weaviate
are local development dependencies. PostgreSQL is HAPI's internal persistence
store; application code and pgAdmin users must not insert directly into HAPI's
tables.

## Backend Component Boundaries

```mermaid
flowchart TD
    API["app/api<br/>HTTP mapping"]
    Workflow["app/workflow<br/>graph assembly and routing"]
    Tools["app/tools<br/>application capability interfaces"]
    RAG["app/rag<br/>retrieval interfaces"]
    Services["app/services<br/>external adapters"]
    Core["app/core<br/>configuration and runtime concerns"]
    Domain["app/domain<br/>durable provider-neutral contracts"]

    API --> Domain
    API -. "Phase 2" .-> Workflow
    Workflow -. "Phase 2" .-> Tools
    Workflow -. "Phase 3" .-> RAG
    Workflow --> Domain
    API --> Services
    Services --> Tools
    RAG -. "Phase 3" .-> Services
    Services --> Domain
    Core --> API
    Core --> Services
```

Solid arrows represent current dependencies. Dotted arrows are planned
extension paths and do not imply implemented behavior. The patient API creates
a request-scoped HAPI adapter, injects it into the summary service through the
read-only FHIR interface, and closes the transport after the request.

## Current Workflow Skeleton

Phase 2.1 introduces only lifecycle mechanics and contains no clinical
behavior:

```mermaid
flowchart LR
    Start(["START"])
    Begin["begin_execution<br/>queued → running"]
    Halt["halt_unimplemented<br/>running → failed"]
    End(["END"])

    Start --> Begin --> Halt --> End
```

The graph wraps the durable `WorkflowState` with an append-only transition
list. An immutable run-scoped context supplies the application-owned clock.
Until later sub-phases add reviewed nodes, every execution ends with the stable
`workflow_not_implemented` failure code.

Boundary rules:

- `api` translates HTTP input and output; workflow rules do not belong there.
- `workflow` owns graph nodes, routing, and graph assembly.
- `tools` defines constrained application capabilities used by graph nodes.
- `rag` owns guideline ingestion and retrieval interfaces.
- `services` contains HAPI FHIR, Weaviate, model, persistence, and audit
  adapters.
- `domain` owns durable types and must not import vendor SDK objects.
- `core` owns validated settings and shared runtime concerns.
- The frontend calls only the application API. It never connects directly to
  HAPI FHIR, PostgreSQL, Weaviate, SQLite, or a model provider.

## Local Data Flow

Health reporting and normalized synthetic patient lookup are implemented:

```mermaid
sequenceDiagram
    participant Browser
    participant UI as React UI
    participant API as FastAPI
    participant Summary as Summary service
    participant DB as SQLite
    participant FHIR as HAPI FHIR
    participant Vector as Weaviate

    Browser->>UI: Load application
    UI->>API: GET /health/live
    API-->>UI: 200 {"status": "ok"}

    opt Explicit readiness request
        Browser->>API: GET /health/ready
        par Dependency probes
            API->>DB: SELECT 1
            API->>FHIR: GET /fhir/metadata
            API->>Vector: GET /.well-known/ready
        end
        API-->>Browser: 200 ready or 503 not_ready
    end

    opt Normalized synthetic patient lookup
        Browser->>API: GET /api/v1/patients/{id}/summary
        API->>Summary: get(validated patient ID)
        Summary->>FHIR: read Patient
        par Bounded clinical searches
            Summary->>FHIR: search approved resource types
        end
        FHIR-->>Summary: confined parsed pages
        Summary-->>API: minimum-necessary PatientSummary
        API-->>Browser: 200 ApiSuccess or safe typed error
    end
```

Readiness responses expose stable dependency states, not raw exceptions,
credentials, connection strings, or patient resources. Patient lookup errors
similarly expose stable application codes rather than HAPI payloads or
transport details.

## Planned Clinical Request Flow

Later phases will extend the existing boundaries in this order:

```mermaid
flowchart LR
    Request["Validated API request"]
    Graph["LangGraph workflow"]
    FHIRTool["FHIR tool interface"]
    FHIRAdapter["HAPI FHIR adapter"]
    Normalize["Minimum patient summary"]
    Retrieval["Guideline retrieval interface"]
    WeaviateAdapter["Weaviate adapter"]
    Model["Provider-neutral model interface"]
    Safety["Deterministic safety and review routing"]
    Response["Qualified response with citations"]
    Audit["Minimal audit metadata"]

    Request --> Graph
    Graph --> FHIRTool --> FHIRAdapter --> Normalize --> Graph
    Graph --> Retrieval --> WeaviateAdapter --> Graph
    Graph --> Model --> Graph
    Graph --> Safety --> Response
    Graph --> Audit
```

Raw FHIR resources, Weaviate results, and model-provider responses are
normalized inside their adapters. Only minimum-necessary, application-owned
types cross into workflow state.

## Storage Ownership

| Store | Owner | Current use | Reset behavior |
|---|---|---|---|
| SQLite | Application backend | Readiness probe and future application state | `make app-data-reset CONFIRM=1` |
| PostgreSQL | HAPI FHIR | HAPI schema and synthetic FHIR cohort | Removed with `make infra-reset CONFIRM=1` |
| Weaviate | Retrieval adapter | Readiness only; no corpus is loaded | Removed with `make infra-reset CONFIRM=1` |

Docker volumes survive `make infra-down`. Reset commands are intentionally
guarded because they delete local development data.

## Safety and Trust Boundaries

- Only synthetic patient data is permitted.
- This project is an educational workflow demonstration, not a medical device.
- Generated output must not be represented as medical advice.
- Patient context, user requests, and retrieved guideline text are untrusted
  inputs.
- Full FHIR resources, prompts containing patient context, secrets, and raw
  document bodies must not be logged.
- Deterministic safety rules and human-review decisions remain explicit domain
  results rather than hidden prompt behavior.
- Local anonymous Weaviate access and documented development credentials are
  not production security controls.

See [Development Safety and Data Policy](SAFETY_AND_DATA_POLICY.md) for the
complete requirements.
