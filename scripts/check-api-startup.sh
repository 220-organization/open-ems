#!/usr/bin/env bash
# FastAPI import + lifespan startup — catches missing imports before deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

echo "Running API startup check (app/main.py lifespan)…" >&2
"${PYTHON}" "${ROOT}/scripts/check-api-startup.py"
