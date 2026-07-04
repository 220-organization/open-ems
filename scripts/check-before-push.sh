#!/usr/bin/env bash
# Pre-push gate: API lifespan startup + UI production build (when ui/ changed).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

APP_CHANGED=0
UI_CHANGED=0

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BASE="${CHECK_BEFORE_PUSH_BASE:-origin/main}"
  if git rev-parse "${BASE}" >/dev/null 2>&1; then
    if git diff --name-only "${BASE}"...HEAD -- app/ db/ requirements.txt 2>/dev/null | grep -q .; then
      APP_CHANGED=1
    fi
    if git diff --name-only "${BASE}"...HEAD -- ui/ 2>/dev/null | grep -q .; then
      UI_CHANGED=1
    fi
  fi
  # Uncommitted changes vs HEAD
  if git diff --name-only HEAD -- app/ db/ requirements.txt 2>/dev/null | grep -q .; then
    APP_CHANGED=1
  fi
  if git diff --name-only HEAD -- ui/ 2>/dev/null | grep -q .; then
    UI_CHANGED=1
  fi
  if git diff --name-only --cached -- app/ db/ requirements.txt 2>/dev/null | grep -q .; then
    APP_CHANGED=1
  fi
  if git diff --name-only --cached -- ui/ 2>/dev/null | grep -q .; then
    UI_CHANGED=1
  fi
else
  APP_CHANGED=1
  UI_CHANGED=1
fi

# Always run API startup when app/ might have changed; override with CHECK_API_STARTUP=0.
if [[ "${CHECK_API_STARTUP:-1}" != "0" ]] && { [[ "${APP_CHANGED}" -eq 1 ]] || [[ "${CHECK_API_STARTUP_FORCE:-0}" == "1" ]]; }; then
  "${ROOT}/scripts/check-api-startup.sh"
else
  echo "Skipping API startup check (no app/ changes)." >&2
fi

if [[ "${UI_CHANGED}" -eq 1 ]] || [[ "${CHECK_UI_BUILD_FORCE:-0}" == "1" ]]; then
  "${ROOT}/scripts/check-ui-production-build.sh"
else
  echo "Skipping UI production build (no ui/ changes)." >&2
fi

echo "Pre-push checks OK" >&2
