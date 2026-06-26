#!/usr/bin/env bash
# Production UI build — same as Dockerfile.ui (RUN npm run build).
# Run before git push to catch compile errors that break deploy on the server.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UI="${ROOT}/ui"

export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}"
export CI="${CI:-true}"
export GENERATE_SOURCEMAP="${GENERATE_SOURCEMAP:-false}"

if [[ ! -f "${UI}/package.json" ]]; then
  echo "ERROR: ${UI}/package.json not found" >&2
  exit 1
fi

if [[ ! -d "${UI}/node_modules" ]]; then
  echo "Installing UI dependencies (npm ci)…" >&2
  (cd "${UI}" && npm ci)
fi

echo "Running production build (ui/)…" >&2
(cd "${UI}" && npm run build)

echo "UI production build OK" >&2
