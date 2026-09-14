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
- `GET /health/ready` — confirms SQLite, HAPI FHIR, and Weaviate readiness.

Grounded generation defaults to the credential-free deterministic provider.
Configure one real provider in `backend/.env` when needed:

```dotenv
# OpenAI
CLINICAL_LLM_PROVIDER=openai
CLINICAL_LLM_API_KEY=replace-with-an-openai-api-key
CLINICAL_LLM_MODEL=gpt-5.6-sol

# Or Anthropic
CLINICAL_LLM_PROVIDER=anthropic
CLINICAL_LLM_API_KEY=replace-with-an-anthropic-api-key
CLINICAL_LLM_ANTHROPIC_MODEL=claude-sonnet-4-6

# Or local Ollama (no API key)
CLINICAL_LLM_PROVIDER=ollama
CLINICAL_LLM_OLLAMA_MODEL=qwen3:4b
CLINICAL_LLM_OLLAMA_BASE_URL=http://localhost:11434
CLINICAL_LLM_OLLAMA_CONTEXT_WINDOW=8192
CLINICAL_LLM_REQUEST_TIMEOUT_SECONDS=180
CLINICAL_LLM_MAX_RETRIES=0
CLINICAL_LLM_MAX_OUTPUT_TOKENS=512
```

Only one provider block should be active. Restart the backend after changing
the provider configuration. Before selecting Ollama, start its local server and
download the configured model:

```bash
ollama pull qwen3:4b
ollama serve
```

Run all backend formatting, linting, typing, and test checks from the repository
root:

```bash
make backend-check
```
