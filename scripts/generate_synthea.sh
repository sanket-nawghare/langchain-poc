#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNTHEA_VERSION="v4.0.0"
SYNTHEA_COMMIT="0185c09ea9d10a822c6f5f3ef9bdcbcbe960c813"
SYNTHEA_JAR_SHA256="ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
SYNTHEA_JAR_URL="https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar"
SYNTHEA_CACHE_DIR="${SYNTHEA_CACHE_DIR:-${REPOSITORY_ROOT}/.tooling/synthea/${SYNTHEA_VERSION}}"
SYNTHEA_OUTPUT_DIR="${SYNTHEA_OUTPUT_DIR:-${REPOSITORY_ROOT}/data/generated/synthea-v4.0.0}"
SYNTHEA_JAR="${SYNTHEA_CACHE_DIR}/synthea-with-dependencies.jar"
SYNTHEA_CONFIG="${REPOSITORY_ROOT}/data/synthetic/synthea.properties"

if [[ -e "${SYNTHEA_OUTPUT_DIR}" ]]; then
  echo "Refusing to mix generated output in existing path: ${SYNTHEA_OUTPUT_DIR}" >&2
  echo "Use 'make synthea-generated-reset CONFIRM=1' before regenerating." >&2
  exit 1
fi

mkdir -p "${SYNTHEA_CACHE_DIR}"

if [[ ! -f "${SYNTHEA_JAR}" ]]; then
  echo "Downloading pinned Synthea ${SYNTHEA_VERSION} artifact..."
  curl \
    --fail \
    --location \
    --retry 3 \
    --output "${SYNTHEA_JAR}.download" \
    "${SYNTHEA_JAR_URL}"
  mv "${SYNTHEA_JAR}.download" "${SYNTHEA_JAR}"
fi

echo "${SYNTHEA_JAR_SHA256}  ${SYNTHEA_JAR}" | sha256sum --check --status

GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
JAVA_VERSION="$(java -version 2>&1 | tr '\n' ' ')"

java -jar "${SYNTHEA_JAR}" \
  -c "${SYNTHEA_CONFIG}" \
  -s 20260727 \
  -cs 104729 \
  -r 20260727 \
  -p 100 \
  -o false \
  -a 45-80 \
  --exporter.baseDirectory="${SYNTHEA_OUTPUT_DIR}" \
  Massachusetts

UV_CACHE_DIR="${REPOSITORY_ROOT}/.uv-cache" \
UV_PYTHON_INSTALL_DIR="${REPOSITORY_ROOT}/.python" \
"${REPOSITORY_ROOT}/.tooling/bin/uv" run --project "${REPOSITORY_ROOT}/backend" \
  python -m scripts.synthetic_cohort write-generation-metadata \
  --output "${SYNTHEA_OUTPUT_DIR}/generation-metadata.json" \
  --config "${SYNTHEA_CONFIG}" \
  --generated-at "${GENERATED_AT}" \
  --java-version "${JAVA_VERSION}" \
  --artifact-path "${SYNTHEA_JAR}" \
  --artifact-sha256 "${SYNTHEA_JAR_SHA256}" \
  --synthea-version "${SYNTHEA_VERSION}" \
  --synthea-commit "${SYNTHEA_COMMIT}"

echo "Generated candidates under ${SYNTHEA_OUTPUT_DIR}"
