# Foundation Decisions

These decisions define the Phase 0 implementation baseline. Changes should be
recorded in the project roadmap's decision log and, when substantial, in a
dedicated architecture decision record.

## Runtime and Package Management

| Area | Decision | Rationale |
|---|---|---|
| Python | CPython 3.12 | Modern typing support with a conservative compatibility target for AI, FHIR, and data libraries |
| Python packages | `uv` with `pyproject.toml` and a committed lockfile | Reproducible environments, fast installs, and managed Python support |
| Node.js | Node.js 24 | Matches the available development environment and provides a current LTS baseline |
| JavaScript packages | pnpm with a committed lockfile and pinned package-manager version | Already available locally, space-efficient, and strict about dependency declarations |
| Backend | FastAPI | Aligns with the Python LangChain and LangGraph ecosystem and provides typed API tooling |
| Frontend | React, Vite, and TypeScript | Supports a small interactive UI and later React Flow visualization |

The host currently has Python 3.14 rather than the selected Python 3.12.
Installing `uv` and using its managed runtime will be handled during application
scaffolding. A contributor must not need to replace their system Python.

## Repository Shape

The project is a monorepo:

```text
.
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP transport and request/response mapping
│   │   ├── core/         # configuration, logging, and shared runtime concerns
│   │   ├── domain/       # provider-neutral schemas and domain rules
│   │   ├── workflow/     # LangGraph state, nodes, routing, and assembly
│   │   ├── tools/        # constrained capabilities exposed to workflows
│   │   ├── rag/          # ingestion and retrieval interfaces
│   │   └── services/     # adapters for FHIR, models, persistence, and audit
│   └── tests/
├── frontend/
│   └── src/
├── data/
│   ├── synthetic/        # clearly labeled, non-real test data
│   └── guidelines/       # source metadata and local development inputs
├── docker/               # service-specific Docker configuration
├── docs/
└── compose.yaml
```

Python modules live under one backend package instead of separate top-level
`langgraph`, `tools`, and `rag` packages. This keeps dependency direction
visible and avoids modifying Python import paths to connect related modules.

## Dependency Boundaries

```text
Frontend -> API -> Workflow -> Domain
                     |
                     +-> Tool interfaces -> FHIR adapter
                     |
                     +-> Retrieval interface -> Weaviate adapter
                     |
                     +-> Model interface -> configured LLM provider
                     |
                     +-> Audit/checkpoint interfaces -> SQLite
```

Rules:

- The API maps transport data to domain types; it does not contain workflow
  logic.
- Workflow nodes depend on domain types and capability interfaces, not vendor
  SDK objects.
- FHIR resources are normalized at the FHIR adapter boundary.
- Weaviate-specific objects do not leave the retrieval adapter.
- Model-provider response objects do not become workflow state.
- Safety decisions are explicit domain results. Deterministic rules are not
  hidden inside prompts.
- The frontend communicates through the API and never connects directly to
  FHIR, Weaviate, SQLite, or an LLM provider.

## Local Storage and Services

| Component | Development role |
|---|---|
| SQLite | Application state, workflow checkpoints, review state, and audit records |
| HAPI FHIR | Read-only source of synthetic patient resources |
| Weaviate | Vector and metadata retrieval for the curated guideline corpus |
| Docker Compose | Reproducible orchestration of local service dependencies |
| Docker volumes | Explicit persistence for local service data |

HAPI FHIR and Weaviate are development dependencies, but the basic backend
liveness endpoint must work without them. Readiness reports their availability.
Exact images, versions, ports, volumes, and health checks are resolved in
Sub-phase 0.4 after inspecting the local images.

## Model Provider Boundary

The workflow will use an application-owned model interface with structured input
and output. OpenAI, Anthropic, Gemini, or Ollama support can be added through
adapters without changing domain types or graph routing.

Foundation health checks and smoke tests must run without an API key or model
network call. Deterministic fake adapters will be used in automated tests.

## Phase Boundaries

Phase 0 creates runnable shells, typed contracts, service configuration, quality
gates, and documentation. It does not:

- Query or seed HAPI FHIR.
- Ingest or search guidelines.
- Call an LLM.
- Implement the production clinical-QA graph.
- Implement clinical safety rules or human approval behavior.

Those capabilities belong to later roadmap phases and will use the boundaries
established here.

