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
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_HOST ?= 127.0.0.1
FRONTEND_PORT ?= 5173
HAPI_FHIR_PORT ?= 8080
FHIR_BASE_URL ?= http://127.0.0.1:$(HAPI_FHIR_PORT)/fhir
FHIR_REQUEST_TIMEOUT_SECONDS ?= 120
BACKEND_BASE_URL ?= http://127.0.0.1:$(BACKEND_PORT)

.PHONY: help setup backend-sync frontend-install dev backend-dev frontend-dev \
	backend-format backend-format-check backend-lint backend-typecheck \
	backend-test backend-check frontend-format frontend-format-check \
	frontend-lint frontend-typecheck frontend-test frontend-check test \
	frontend-build pre-commit-install pre-commit check infra-config infra-up \
	infra-status infra-logs infra-down infra-reset app-data-reset \
	synthea-generate synthea-select synthea-verify synthea-cohort \
	synthea-ensure synthea-generated-reset synthea-fixtures-reset \
	fhir-seed fhir-verify fhir-reset phase2-live-gate \
	guidelines-fetch guidelines-verify guidelines-chunk guidelines-index \
	guidelines-index-verify guidelines-index-reset phase3-retrieval-live-gate

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
	$(UV_ENV) $(UV) run --project backend uvicorn app.main:app --app-dir backend \
		--host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

frontend-dev: ## Start the Vite development server
	$(PNPM) --dir frontend exec vite --host $(FRONTEND_HOST) --port $(FRONTEND_PORT)

backend-format: $(UV_BIN) ## Format backend Python files
	$(UV_ENV) $(UV) run --project backend ruff format backend scripts

backend-format-check: $(UV_BIN) ## Check backend Python formatting
	$(UV_ENV) $(UV) run --project backend ruff format --check backend scripts

backend-lint: $(UV_BIN) ## Lint backend Python files
	$(UV_ENV) $(UV) run --project backend ruff check backend scripts

backend-typecheck: $(UV_BIN) ## Type-check the backend
	$(UV_ENV) $(UV) run --project backend mypy --config-file backend/pyproject.toml \
		backend/app backend/tests scripts

backend-test: $(UV_BIN) ## Run backend tests
	$(UV_ENV) $(UV) run --project backend pytest -c backend/pyproject.toml

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

synthea-generate: $(UV_BIN) ## Generate the ignored deterministic Synthea candidate pool
	bash scripts/generate_synthea.sh

synthea-select: $(UV_BIN) ## Select and write the reviewed synthetic cohort
	$(UV_ENV) $(UV) run --project backend python -m scripts.synthetic_cohort select \
		--candidate-dir data/generated/synthea-v4.0.0/fhir \
		--generation-metadata data/generated/synthea-v4.0.0/generation-metadata.json \
		--fixture-dir data/synthetic/fhir \
		--manifest data/synthetic/cohort-manifest.json \
		--lock data/synthetic/cohort-lock.json

synthea-verify: $(UV_BIN) ## Verify local cohort structure and locked checksums
	$(UV_ENV) $(UV) run --project backend python -m scripts.synthetic_cohort verify \
		--manifest data/synthetic/cohort-manifest.json \
		--lock data/synthetic/cohort-lock.json

synthea-cohort: synthea-generate synthea-select synthea-verify ## Generate and verify the reviewed cohort

synthea-ensure: $(UV_BIN) ## Generate missing local cohort output or verify existing output
	@if test -f data/synthetic/cohort-manifest.json && \
		test -d data/synthetic/fhir; then \
		$(MAKE) synthea-verify; \
	elif test -e data/synthetic/cohort-manifest.json || \
		test -e data/synthetic/fhir; then \
		echo "Partial selected cohort found; run make synthea-fixtures-reset CONFIRM=1."; \
		exit 1; \
	elif test -f data/generated/synthea-v4.0.0/generation-metadata.json && \
		test -d data/generated/synthea-v4.0.0/fhir; then \
		$(MAKE) synthea-select synthea-verify; \
	elif test -e data/generated/synthea-v4.0.0; then \
		echo "Partial candidate pool found; run make synthea-generated-reset CONFIRM=1."; \
		exit 1; \
	else \
		$(MAKE) synthea-cohort; \
	fi

synthea-generated-reset: ## Delete ignored Synthea candidates (requires CONFIRM=1)
	@test "$(CONFIRM)" = "1" || \
		{ echo "Refusing to delete generated candidates. Re-run with CONFIRM=1."; exit 1; }
	rm --recursive --force -- data/generated/synthea-v4.0.0

synthea-fixtures-reset: ## Delete local selected cohort output (requires CONFIRM=1)
	@test "$(CONFIRM)" = "1" || \
		{ echo "Refusing to delete selected fixtures. Re-run with CONFIRM=1."; exit 1; }
	rm --recursive --force -- data/synthetic/fhir
	rm --force -- data/synthetic/cohort-manifest.json

guidelines-fetch: $(UV_BIN) ## Download and verify the reviewed local guideline corpus
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_corpus fetch \
		--lock data/guidelines/corpus-lock.json \
		--document-dir data/guidelines/documents

guidelines-verify: $(UV_BIN) ## Verify local guidelines against reviewed checksums
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_corpus verify \
		--lock data/guidelines/corpus-lock.json \
		--document-dir data/guidelines/documents

guidelines-chunk: $(UV_BIN) ## Build and verify ignored deterministic guideline chunks
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_chunks \
		--corpus-lock data/guidelines/corpus-lock.json \
		--document-dir data/guidelines/documents \
		--chunk-lock data/guidelines/chunk-lock.json \
		--output data/guidelines/processed/chunks.json

guidelines-index: guidelines-chunk ## Idempotently index verified guideline chunks in local Weaviate
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_index sync \
		--chunk-lock data/guidelines/chunk-lock.json \
		--input data/guidelines/processed/chunks.json

guidelines-index-verify: guidelines-chunk ## Verify exact local guideline index IDs and metadata
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_index verify \
		--chunk-lock data/guidelines/chunk-lock.json \
		--input data/guidelines/processed/chunks.json

guidelines-index-reset: $(UV_BIN) ## Delete only the guideline collection (requires CONFIRM=1)
	@test "$(CONFIRM)" = "1" || \
		{ echo "Refusing to delete guideline index. Re-run with CONFIRM=1."; exit 1; }
	$(UV_ENV) $(UV) run --project backend python -m scripts.guideline_index reset \
		--confirm-collection ClinicalGuidelineChunkV1

phase3-retrieval-live-gate: guidelines-index-verify ## Run deidentified Phase 3.5 retrieval evaluation
	$(UV_ENV) $(UV) run --project backend python -m scripts.phase3_retrieval_live_gate \
		--evaluation data/guidelines/retrieval-evaluation.json \
		--corpus-lock data/guidelines/corpus-lock.json

fhir-seed: synthea-ensure ## Idempotently seed the locked cohort into local HAPI
	$(UV_ENV) $(UV) run --project backend python -m scripts.fhir_seed seed \
		--base-url "$(FHIR_BASE_URL)" \
		--manifest data/synthetic/cohort-manifest.json \
		--lock data/synthetic/cohort-lock.json \
		--timeout-seconds "$(FHIR_REQUEST_TIMEOUT_SECONDS)"

fhir-verify: synthea-ensure ## Verify the locked cohort in local HAPI
	$(UV_ENV) $(UV) run --project backend python -m scripts.fhir_seed verify \
		--base-url "$(FHIR_BASE_URL)" \
		--manifest data/synthetic/cohort-manifest.json \
		--lock data/synthetic/cohort-lock.json \
		--timeout-seconds "$(FHIR_REQUEST_TIMEOUT_SECONDS)"

fhir-reset: synthea-ensure ## Reset only local HAPI data (requires CONFIRM=1)
	CONFIRM="$(CONFIRM)" FHIR_BASE_URL="$(FHIR_BASE_URL)" \
		FHIR_REQUEST_TIMEOUT_SECONDS="$(FHIR_REQUEST_TIMEOUT_SECONDS)" \
		bash scripts/reset_local_hapi.sh

phase2-live-gate: fhir-verify ## Run the opt-in seeded Phase 2 API integration gate
	$(UV_ENV) $(UV) run --project backend python -m scripts.phase2_live_gate \
		--base-url "$(BACKEND_BASE_URL)" \
		--manifest data/synthetic/cohort-manifest.json

check: backend-check frontend-check frontend-build infra-config ## Run every required local quality check
