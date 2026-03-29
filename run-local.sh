#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Local API against Docker PostgreSQL + Flyway migrations (see README / docker-compose.yml).
# WSL/Ubuntu/macOS: requires Docker Compose v2.

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems}"

# Default 9220 avoids clashes with other tools on 8090 (e.g. admin-portal). Override: PORT=8090 ./run-local.sh
_port_busy() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -i ":${p}" -sTCP:LISTEN >/dev/null 2>&1
  else
    # No lsof: try a quick bash /dev/tcp check (connect fails if nothing listens)
    if command -v timeout >/dev/null 2>&1; then
      timeout 0.1 bash -c "echo > /dev/tcp/127.0.0.1/${p}" 2>/dev/null
    else
      (echo > /dev/tcp/127.0.0.1/${p}) 2>/dev/null
    fi
  fi
}

_resolve_port() {
  local want="${PORT:-9220}"
  local p
  for p in $(seq "${want}" $((want + 30))); do
    if ! _port_busy "${p}"; then
      echo "${p}"
      return 0
    fi
  done
  echo "No free TCP port found from ${want} upward (30 tries)." >&2
  return 1
}

PORT="$(_resolve_port)"
export PORT

docker compose up -d db

echo "Waiting for PostgreSQL..."
for _ in $(seq 1 90); do
  if docker compose exec -T db pg_isready -U openems -d openems >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! docker compose exec -T db pg_isready -U openems -d openems >/dev/null 2>&1; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

docker compose run --rm migrate

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -r requirements.txt

_open_swagger_ui() {
  local url="http://127.0.0.1:${PORT}/docs"
  if [[ -n "${BROWSER:-}" ]]; then
    "$BROWSER" "$url" 2>/dev/null && return
  fi
  case "$(uname -s)" in
    Darwin)
      open "$url"
      ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        cmd.exe /c start "" "$url" 2>/dev/null || explorer.exe "$url" 2>/dev/null || true
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
      elif command -v wslview >/dev/null 2>&1; then
        wslview "$url" 2>/dev/null || true
      else
        echo "Swagger UI: $url" >&2
      fi
      ;;
    *)
      echo "Swagger UI: $url" >&2
      ;;
  esac
}

_wait_for_openapi() {
  local url="http://127.0.0.1:${PORT}/openapi.json"
  local i
  for i in $(seq 1 150); do
    if command -v curl >/dev/null 2>&1 && curl -sf --connect-timeout 1 --max-time 2 "$url" >/dev/null; then
      return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
      sleep 2
      return 0
    fi
    sleep 0.2
  done
  echo "Timed out waiting for $url — open /docs manually if the app is up." >&2
  return 1
}

echo "Starting API at http://127.0.0.1:${PORT} (Swagger at /docs)"
uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT}" &
UVICORN_PID=$!
trap 'kill -TERM "${UVICORN_PID}" 2>/dev/null || true' INT TERM

_wait_for_openapi || true
echo "Opening Swagger UI in the default browser…"
_open_swagger_ui || true

wait "${UVICORN_PID}"
trap - INT TERM
