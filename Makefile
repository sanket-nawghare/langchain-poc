PYTHON ?= python3
PNPM ?= pnpm
UV_VERSION ?= 0.11.32
UV_BIN := .tooling/bin/uv
UV := $(UV_BIN)
UV_CACHE_DIR ?= .uv-cache
UV_PYTHON_INSTALL_DIR ?= .python
UV_ENV = UV_CACHE_DIR=$(UV_CACHE_DIR) UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_INSTALL_DIR)

.PHONY: help setup backend-sync frontend-install dev backend-dev frontend-dev \
	backend-test frontend-test test frontend-build check

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

backend-test: $(UV_BIN) ## Run backend tests
	$(UV_ENV) $(UV) run --project backend pytest

frontend-test: ## Run frontend tests
	$(PNPM) --dir frontend test

test: backend-test frontend-test ## Run backend and frontend tests

frontend-build: ## Type-check and build the frontend
	$(PNPM) --dir frontend build

check: test frontend-build ## Run all currently configured checks
