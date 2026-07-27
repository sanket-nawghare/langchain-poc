# AI Clinical Workflow Engine

An educational, open-source clinical workflow orchestration project using
LangChain, LangGraph, FHIR, and retrieval-augmented generation with synthetic
patient data.

Application shells:

- [FastAPI backend](backend/README.md)
- [React frontend](frontend/README.md)

After installing Python 3, pnpm, and Node.js 24:

```bash
make setup
make infra-up
make dev
```

`make setup` bootstraps a pinned, project-local `uv`, which then installs the
managed Python 3.12 runtime and locked backend dependencies. Run `make help` to
list the available development commands.

Run every required local quality gate with:

```bash
make check
```

Project documents:

- [Original concept and architecture](plan.md)
- [Phased roadmap and progress tracker](docs/PROJECT_ROADMAP.md)
- [Phase 0 foundations execution plan](docs/PHASE_0_FOUNDATIONS.md)
- [MVP scope](docs/MVP_SCOPE.md)
- [Foundation decisions](docs/FOUNDATION_DECISIONS.md)
- [Contracts and configuration](docs/CONTRACTS_AND_CONFIGURATION.md)
- [Development safety and data policy](docs/SAFETY_AND_DATA_POLICY.md)
- [Quality gates and CI](docs/QUALITY_GATES.md)
- [Local infrastructure](docker/README.md)
