PYTHON ?= python3
PNPM ?= pnpm
UV_VERSION ?= 0.11.32
UV_BIN := .tooling/bin/uv
UV := $(UV_BIN)
UV_CACHE_DIR ?= .uv-cache
UV_PYTHON_INSTALL_DIR ?= .python
UV_ENV = UV_CACHE_DIR=$(UV_CACHE_DIR) UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_INSTALL_DIR)
PRE_COMMIT_HOME ?= .pre-commit-cache
PRE_COMMIT_ENV = PRE_COMMIT_HOME=$(PRE_COMMIT_HOME)

.PHONY: help setup backend-sync frontend-install dev backend-dev frontend-dev \
	backend-format backend-format-check backend-lint backend-typecheck \
	backend-test backend-check frontend-format frontend-format-check \
	frontend-lint frontend-typecheck frontend-test frontend-check test \
	frontend-build pre-commit-install pre-commit check infra-config infra-up \
	infra-status infra-logs infra-down infra-reset app-data-reset

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: backend-sync frontend-install ## Install backend and frontend dependencies

$(UV_BIN):
	$(PYTHON) -m venv .tooling
	.tooling/bin/python -m pip install "uv==$(UV_VERSION)"

backend-sync: $(UV_BIN) ## Install locked backend dependencies
	$(UV_ENV) $(UV) sync --project backend

frontend-install: ## Install locked frontend dependencies
	$(PNPM) --dir frontend install --frozen-lockfile

dev: ## Start backend and frontend development servers
	$(MAKE) --jobs=2 backend-dev frontend-dev

backend-dev: $(UV_BIN) ## Start the FastAPI development server
	$(UV_ENV) $(UV) run --project backend uvicorn app.main:app --app-dir backend --reload

frontend-dev: ## Start the Vite development server
	$(PNPM) --dir frontend dev

backend-format: $(UV_BIN) ## Format backend Python files
	$(UV_ENV) $(UV) run --project backend ruff format backend

backend-format-check: $(UV_BIN) ## Check backend Python formatting
	$(UV_ENV) $(UV) run --project backend ruff format --check backend

backend-lint: $(UV_BIN) ## Lint backend Python files
	$(UV_ENV) $(UV) run --project backend ruff check backend

backend-typecheck: $(UV_BIN) ## Type-check the backend
	$(UV_ENV) $(UV) run --project backend mypy --config-file backend/pyproject.toml backend/app backend/tests

backend-test: $(UV_BIN) ## Run backend tests
	$(UV_ENV) $(UV) run --project backend pytest

backend-check: backend-format-check backend-lint backend-typecheck backend-test ## Run all backend quality checks

frontend-format: ## Format frontend files
	$(PNPM) --dir frontend format

frontend-format-check: ## Check frontend formatting
	$(PNPM) --dir frontend format:check

frontend-lint: ## Lint frontend source
	$(PNPM) --dir frontend lint

frontend-typecheck: ## Type-check the frontend
	$(PNPM) --dir frontend typecheck

frontend-test: ## Run frontend tests
	$(PNPM) --dir frontend test

frontend-check: frontend-format-check frontend-lint frontend-typecheck frontend-test ## Run all frontend quality checks

test: backend-test frontend-test ## Run backend and frontend tests

frontend-build: ## Type-check and build the frontend
	$(PNPM) --dir frontend build

pre-commit-install: $(UV_BIN) ## Install repository pre-commit hooks
	$(PRE_COMMIT_ENV) $(UV_ENV) $(UV) run --project backend pre-commit install

pre-commit: $(UV_BIN) ## Run pre-commit hooks against all files
	$(PRE_COMMIT_ENV) $(UV_ENV) $(UV) run --project backend pre-commit run --all-files

infra-config: ## Validate the Docker Compose configuration
	docker compose config --quiet

infra-up: ## Start local infrastructure and wait for healthy services
	docker compose up --detach --build --wait --wait-timeout 300

infra-status: ## Show local infrastructure status
	docker compose ps

infra-logs: ## Follow local infrastructure logs
	docker compose logs --follow --tail=100

infra-down: ## Stop containers while retaining local data
	docker compose down

infra-reset: ## Delete all local infrastructure volumes (requires CONFIRM=1)
	@test "$(CONFIRM)" = "1" || \
		{ echo "Refusing to delete volumes. Re-run with CONFIRM=1."; exit 1; }
	docker compose down --volumes

app-data-reset: ## Delete the local SQLite database (requires CONFIRM=1)
	@test "$(CONFIRM)" = "1" || \
		{ echo "Refusing to delete SQLite data. Re-run with CONFIRM=1."; exit 1; }
	rm --force -- data/clinical_workflow.db
	rm --force -- data/clinical_workflow.db-shm
	rm --force -- data/clinical_workflow.db-wal

check: backend-check frontend-check frontend-build infra-config ## Run every required local quality check
