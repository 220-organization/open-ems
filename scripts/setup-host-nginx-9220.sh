#!/usr/bin/env bash
# Install host nginx on port 9220 (Hetzner LB target). Docker web binds 127.0.0.1:19220 only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAINT_DIR=/var/www/open-ems-maintenance
CONF=/etc/nginx/sites-available/open-ems-9220.conf
ENABLED=/etc/nginx/sites-enabled/open-ems-9220.conf

if ! command -v nginx >/dev/null 2>&1; then
  echo "Installing nginx …"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y nginx
fi

mkdir -p "$MAINT_DIR"
cp "$ROOT/docker/host-maintenance.html" "$MAINT_DIR/deploy-maintenance.html"
cp "$ROOT/docker/host-nginx-open-ems.conf" "$CONF"
ln -sf "$CONF" "$ENABLED"

# Drop default site if it conflicts on port 80 only; open-ems uses 9220.
if [[ -f /etc/nginx/sites-enabled/default ]]; then
  rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl enable nginx
systemctl restart nginx

echo "Host nginx OK on :9220 → docker web 127.0.0.1:19220"
echo "Hetzner LB health check: HTTP GET /lb-health (expect 2xx)"
