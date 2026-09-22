#!/usr/bin/env bash
# Migrate marketplace tables + photo files from activecharge admin_portal → open-ems.
# Intended to run on the deploy host after `docker compose up` (see .github/workflows/deploy.yml).
#
# Usage:
#   ./scripts/migrate_marketplace_from_admin_portal.sh
#
# Env overrides:
#   ADMIN_PORTAL_DB_CONTAINER — source Postgres container (default: admin-portal-db)
#   OPENEMS_COMPOSE_DIR       — open-ems tree with compose (default: script repo root)
#   OPENEMS_DB_SERVICE        — compose service name for Postgres (default: db)
#   OPENEMS_VOLUME            — docker volume for uploads (default: open_ems_marketplace_files
#                               or project-prefixed open-ems_open_ems_marketplace_files)
#   MARKETPLACE_SRC_DIRS      — host paths with surviving photo files
#   MARKETPLACE_MIGRATE_FORCE=1 — re-run even when openems already has marketplace rows
#   MARKETPLACE_MIGRATE_MARKER — skip file after success (default:
#                               /var/lib/220km/marketplace-migrated-to-openems)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENEMS_COMPOSE_DIR="${OPENEMS_COMPOSE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
ADMIN_PORTAL_DB_CONTAINER="${ADMIN_PORTAL_DB_CONTAINER:-admin-portal-db}"
OPENEMS_DB_SERVICE="${OPENEMS_DB_SERVICE:-db}"
OPENEMS_VOLUME="${OPENEMS_VOLUME:-}"
MARKETPLACE_SRC_DIRS="${MARKETPLACE_SRC_DIRS:-/var/lib/220km/marketplace /220/activecharge/admin-portal/data/marketplace}"
MARKETPLACE_MIGRATE_MARKER="${MARKETPLACE_MIGRATE_MARKER:-/var/lib/220km/marketplace-migrated-to-openems}"
MARKETPLACE_MIGRATE_FORCE="${MARKETPLACE_MIGRATE_FORCE:-0}"

DUMP_DIR="${DUMP_DIR:-/tmp/marketplace-migrate-$$}"
mkdir -p "$DUMP_DIR"
trap 'rm -rf "$DUMP_DIR"' EXIT

cd "$OPENEMS_COMPOSE_DIR"

resolve_openems_volume() {
  if [[ -n "$OPENEMS_VOLUME" ]]; then
    echo "$OPENEMS_VOLUME"
    return
  fi
  # Compose project name is usually the directory name ("open-ems").
  local candidates=(
    open-ems_open_ems_marketplace_files
    open_ems_marketplace_files
  )
  local vol
  for vol in "${candidates[@]}"; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
      echo "$vol"
      return
    fi
  done
  # Create/use the compose-declared name via project prefix.
  echo "open-ems_open_ems_marketplace_files"
}

openems_psql() {
  docker compose exec -T "$OPENEMS_DB_SERVICE" \
    psql -U openems -d openems -v ON_ERROR_STOP=1 "$@"
}

admin_portal_pg_dump() {
  docker exec "$ADMIN_PORTAL_DB_CONTAINER" \
    pg_dump -U admin_portal -d admin_portal --data-only --inserts \
    -t marketplace_location -t marketplace_info_payment
}

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required on the deploy host" >&2
  exit 1
fi

if ! docker inspect "$ADMIN_PORTAL_DB_CONTAINER" >/dev/null 2>&1; then
  echo "Skip marketplace migrate: container ${ADMIN_PORTAL_DB_CONTAINER} not found (admin-portal not on this host?)."
  exit 0
fi

if ! docker compose ps --status running --services 2>/dev/null | grep -qx "$OPENEMS_DB_SERVICE"; then
  # Older docker compose may not support --status; fall back.
  if ! docker compose exec -T "$OPENEMS_DB_SERVICE" pg_isready -U openems -d openems >/dev/null 2>&1; then
    echo "ERROR: open-ems db service '${OPENEMS_DB_SERVICE}' is not ready in ${OPENEMS_COMPOSE_DIR}" >&2
    exit 1
  fi
fi

# Wait for Flyway V35 tables (api depends on migrate, but race is still possible).
for _ in $(seq 1 30); do
  if openems_psql -tAc "SELECT to_regclass('public.marketplace_location')" | grep -q marketplace_location; then
    break
  fi
  sleep 2
done
if ! openems_psql -tAc "SELECT to_regclass('public.marketplace_location')" | grep -q marketplace_location; then
  echo "ERROR: marketplace_location table missing — Flyway V35 did not apply?" >&2
  exit 1
fi

TARGET_COUNT="$(openems_psql -tAc "SELECT count(*) FROM marketplace_location" | tr -d '[:space:]')"
if [[ "${MARKETPLACE_MIGRATE_FORCE}" != "1" ]]; then
  if [[ -f "$MARKETPLACE_MIGRATE_MARKER" ]]; then
    echo "Skip marketplace migrate: marker exists (${MARKETPLACE_MIGRATE_MARKER}). Set MARKETPLACE_MIGRATE_FORCE=1 to re-run."
    exit 0
  fi
  if [[ "${TARGET_COUNT}" =~ ^[0-9]+$ ]] && [[ "$TARGET_COUNT" -gt 0 ]]; then
    echo "Skip marketplace migrate: openems already has ${TARGET_COUNT} marketplace_location row(s)."
    mkdir -p "$(dirname "$MARKETPLACE_MIGRATE_MARKER")"
    date -u +%Y-%m-%dT%H:%M:%SZ >"$MARKETPLACE_MIGRATE_MARKER"
    exit 0
  fi
fi

echo "Dumping marketplace tables from Docker container ${ADMIN_PORTAL_DB_CONTAINER}…"
admin_portal_pg_dump >"$DUMP_DIR/marketplace_data.sql"

# Rewrite absolute :8090 photo URLs → relative /api/marketplace-files paths.
sed -E \
  -e 's|https?://220-km\.com:8090/marketplace-files/|/api/marketplace-files/|g' \
  -e 's|/marketplace-files/|/api/marketplace-files/|g' \
  "$DUMP_DIR/marketplace_data.sql" >"$DUMP_DIR/marketplace_data_rewritten.sql"

echo "Restoring into open-ems db (compose service ${OPENEMS_DB_SERVICE})…"
openems_psql <<'SQL'
TRUNCATE marketplace_info_payment, marketplace_location CASCADE;
SQL
openems_psql -f - <"$DUMP_DIR/marketplace_data_rewritten.sql"

openems_psql <<'SQL'
UPDATE marketplace_location
SET
  parking_photos = replace(
    replace(parking_photos::text, 'https://220-km.com:8090/marketplace-files/', '/api/marketplace-files/'),
    '/marketplace-files/', '/api/marketplace-files/'
  )::jsonb,
  connection_point_photos = replace(
    replace(connection_point_photos::text, 'https://220-km.com:8090/marketplace-files/', '/api/marketplace-files/'),
    '/marketplace-files/', '/api/marketplace-files/'
  )::jsonb,
  distribution_contract_photos = replace(
    replace(distribution_contract_photos::text, 'https://220-km.com:8090/marketplace-files/', '/api/marketplace-files/'),
    '/marketplace-files/', '/api/marketplace-files/'
  )::jsonb;
SQL

VOLUME_NAME="$(resolve_openems_volume)"
echo "Copying surviving photo files into Docker volume ${VOLUME_NAME}…"
TMP_PHOTOS="$DUMP_DIR/photos"
mkdir -p "$TMP_PHOTOS"
for src in $MARKETPLACE_SRC_DIRS; do
  if [[ -d "$src" ]]; then
    echo "  from $src"
    cp -a "$src"/. "$TMP_PHOTOS"/ 2>/dev/null || true
  else
    echo "  skip missing $src"
  fi
done

docker run --rm \
  -v "${VOLUME_NAME}:/dest" \
  -v "${TMP_PHOTOS}:/src:ro" \
  alpine:3.20 \
  sh -c 'mkdir -p /dest && cp -a /src/. /dest/ && ls -la /dest | head'

mkdir -p "$(dirname "$MARKETPLACE_MIGRATE_MARKER")"
date -u +%Y-%m-%dT%H:%M:%SZ >"$MARKETPLACE_MIGRATE_MARKER"

FINAL_COUNT="$(openems_psql -tAc "SELECT count(*) FROM marketplace_location" | tr -d '[:space:]')"
echo "Done. marketplace_location rows=${FINAL_COUNT}. Marker: ${MARKETPLACE_MIGRATE_MARKER}"
