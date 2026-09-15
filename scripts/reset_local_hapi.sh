#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FHIR_BASE_URL="${FHIR_BASE_URL:-http://127.0.0.1:8080/fhir}"
FHIR_REQUEST_TIMEOUT_SECONDS="${FHIR_REQUEST_TIMEOUT_SECONDS:-120}"
HAPI_VOLUME="clinical-workflow-hapi-postgres"

if [[ "${CONFIRM:-}" != "1" ]]; then
  echo "Refusing to reset HAPI. Re-run with CONFIRM=1." >&2
  exit 1
fi

cd "${REPOSITORY_ROOT}"

UV_CACHE_DIR="${REPOSITORY_ROOT}/.uv-cache" \
UV_PYTHON_INSTALL_DIR="${REPOSITORY_ROOT}/.python" \
"${REPOSITORY_ROOT}/.tooling/bin/uv" run --project "${REPOSITORY_ROOT}/backend" \
  python -m scripts.fhir_seed check-target \
  --base-url "${FHIR_BASE_URL}" \
  --timeout-seconds "${FHIR_REQUEST_TIMEOUT_SECONDS}"

VOLUME_PROJECT="$(
  docker volume inspect \
    --format '{{ index .Labels "com.docker.compose.project" }}' \
    "${HAPI_VOLUME}"
)"
if [[ "${VOLUME_PROJECT}" != "clinical-workflow" ]]; then
  echo "Refusing to delete an unexpected Docker volume." >&2
  exit 1
fi

docker compose stop hapi-fhir hapi-db
docker compose rm --force --stop hapi-fhir hapi-db
docker volume rm "${HAPI_VOLUME}"
docker compose up --detach --wait --wait-timeout 300 hapi-db hapi-fhir

UV_CACHE_DIR="${REPOSITORY_ROOT}/.uv-cache" \
UV_PYTHON_INSTALL_DIR="${REPOSITORY_ROOT}/.python" \
"${REPOSITORY_ROOT}/.tooling/bin/uv" run --project "${REPOSITORY_ROOT}/backend" \
  python -m scripts.fhir_seed verify-empty \
  --base-url "${FHIR_BASE_URL}" \
  --manifest "${REPOSITORY_ROOT}/data/synthetic/cohort-manifest.json" \
  --lock "${REPOSITORY_ROOT}/data/synthetic/cohort-lock.json" \
  --timeout-seconds "${FHIR_REQUEST_TIMEOUT_SECONDS}"

echo "Reset the local HAPI PostgreSQL volume; Weaviate data was retained."
