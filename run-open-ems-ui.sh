#!/usr/bin/env bash
# React dev server for Power flow — same idea as admin-portal/run-admin-ui.sh
set -euo pipefail

cd "$(dirname "$0")" || exit
cd ui

# Default UI port (API from ./run-local.sh is usually 9220)
UI_PORT="${UI_PORT:-3090}"
lsof -ti "tcp:${UI_PORT}" | xargs kill -kill 2>/dev/null || true

if [[ ! -d node_modules ]]; then
  echo "Installing UI dependencies..."
  npm install
fi

# Point at the FastAPI process (override if ./run-local.sh picked another PORT)
export REACT_APP_API_BASE_URL="${REACT_APP_API_BASE_URL:-http://127.0.0.1:9220}"

echo "Open EMS UI → http://127.0.0.1:${UI_PORT} (API: ${REACT_APP_API_BASE_URL})"
PORT="${UI_PORT}" npm start
