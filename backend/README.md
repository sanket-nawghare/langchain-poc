# Backend

The backend is a FastAPI application. From the repository root, install the
development dependencies and run:

```bash
cp backend/.env.example backend/.env
make backend-sync
make backend-dev
```

The Makefile bootstraps a pinned, project-local `uv` and uses it to manage the
Python 3.12 environment. The `.env` copy is optional while using the safe local
defaults, but it is the place for local overrides and secrets. It is ignored by
Git and must not be committed.

The initial endpoints are:

- `GET /health/live` — confirms that the API process is running.
- `GET /health/ready` — confirms foundation readiness. Dependency-aware checks
  will be added in Phase 0.4.
