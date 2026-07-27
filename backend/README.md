# Backend

The backend is a FastAPI application. From the repository root, install the
development dependencies and run:

```bash
make backend-sync
make backend-dev
```

The Makefile bootstraps a pinned, project-local `uv` and uses it to manage the
Python 3.12 environment.

The initial endpoints are:

- `GET /health/live` — confirms that the API process is running.
- `GET /health/ready` — confirms foundation readiness. Dependency-aware checks
  will be added in Phase 0.4.
