#!/usr/bin/env bash
# Migrate marketplace tables + photo files from activecharge admin_portal → open-ems.
# Run on the deploy host (or any host that can reach both Postgres instances and Docker).
#
# Usage:
#   ./scripts/migrate_marketplace_from_admin_portal.sh
#
# Env overrides:
#   ADMIN_PORTAL_PG_*  — source DB (defaults match docker-compose admin-portal-db)
#   OPENEMS_PG_*       — target DB
#   MARKETPLACE_SRC_DIRS — space-separated host paths with surviving photo files
#   OPENEMS_VOLUME     — docker volume name for uploads (default open_ems_marketplace_files)

set -euo pipefail

ADMIN_PORTAL_PG_HOST="${ADMIN_PORTAL_PG_HOST:-127.0.0.1}"
ADMIN_PORTAL_PG_PORT="${ADMIN_PORTAL_PG_PORT:-5432}"
ADMIN_PORTAL_PG_USER="${ADMIN_PORTAL_PG_USER:-admin_portal}"
ADMIN_PORTAL_PG_DB="${ADMIN_PORTAL_PG_DB:-admin_portal}"
ADMIN_PORTAL_PG_PASSWORD="${ADMIN_PORTAL_PG_PASSWORD:-admin_portal}"

OPENEMS_PG_HOST="${OPENEMS_PG_HOST:-127.0.0.1}"
OPENEMS_PG_PORT="${OPENEMS_PG_PORT:-5433}"
OPENEMS_PG_USER="${OPENEMS_PG_USER:-openems}"
OPENEMS_PG_DB="${OPENEMS_PG_DB:-openems}"
OPENEMS_PG_PASSWORD="${OPENEMS_PG_PASSWORD:-openems}"

OPENEMS_VOLUME="${OPENEMS_VOLUME:-open_ems_marketplace_files}"
MARKETPLACE_SRC_DIRS="${MARKETPLACE_SRC_DIRS:-/var/lib/220km/marketplace /220/activecharge/admin-portal/data/marketplace}"

DUMP_DIR="${DUMP_DIR:-/tmp/marketplace-migrate-$$}"
mkdir -p "$DUMP_DIR"
trap 'rm -rf "$DUMP_DIR"' EXIT

export PGPASSWORD="$ADMIN_PORTAL_PG_PASSWORD"
echo "Dumping marketplace tables from ${ADMIN_PORTAL_PG_HOST}:${ADMIN_PORTAL_PG_PORT}/${ADMIN_PORTAL_PG_DB}…"
pg_dump \
  -h "$ADMIN_PORTAL_PG_HOST" -p "$ADMIN_PORTAL_PG_PORT" -U "$ADMIN_PORTAL_PG_USER" -d "$ADMIN_PORTAL_PG_DB" \
  --data-only --inserts \
  -t marketplace_location -t marketplace_info_payment \
  > "$DUMP_DIR/marketplace_data.sql"

# Rewrite absolute :8090 photo URLs → relative /api/marketplace-files paths in the dump text
# (also covers relative /marketplace-files/ left from older rows).
sed -E \
  -e 's|https?://220-km\.com:8090/marketplace-files/|/api/marketplace-files/|g' \
  -e 's|/marketplace-files/|/api/marketplace-files/|g' \
  "$DUMP_DIR/marketplace_data.sql" > "$DUMP_DIR/marketplace_data_rewritten.sql"

export PGPASSWORD="$OPENEMS_PG_PASSWORD"
echo "Restoring into ${OPENEMS_PG_HOST}:${OPENEMS_PG_PORT}/${OPENEMS_PG_DB}…"
# Truncate target first so re-runs are idempotent (FK: payments then locations).
psql -h "$OPENEMS_PG_HOST" -p "$OPENEMS_PG_PORT" -U "$OPENEMS_PG_USER" -d "$OPENEMS_PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
TRUNCATE marketplace_info_payment, marketplace_location CASCADE;
SQL
psql -h "$OPENEMS_PG_HOST" -p "$OPENEMS_PG_PORT" -U "$OPENEMS_PG_USER" -d "$OPENEMS_PG_DB" -v ON_ERROR_STOP=1 \
  -f "$DUMP_DIR/marketplace_data_rewritten.sql"

# Rewrite any leftover absolute URLs already in JSONB after restore (belt-and-suspenders).
psql -h "$OPENEMS_PG_HOST" -p "$OPENEMS_PG_PORT" -U "$OPENEMS_PG_USER" -d "$OPENEMS_PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
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

echo "Copying surviving photo files into Docker volume ${OPENEMS_VOLUME}…"
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

# Prefer docker volume mount helper if docker is available.
if command -v docker >/dev/null 2>&1; then
  docker run --rm \
    -v "${OPENEMS_VOLUME}:/dest" \
    -v "${TMP_PHOTOS}:/src:ro" \
    alpine:3.20 \
    sh -c 'mkdir -p /dest && cp -a /src/. /dest/ && ls -la /dest | head'
else
  echo "docker not found — photos left in $TMP_PHOTOS; copy manually into the api container volume."
  trap - EXIT
fi

echo "Done. Verify: SELECT count(*) FROM marketplace_location; and /api/marketplace/locations"
