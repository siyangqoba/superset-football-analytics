#!/usr/bin/env bash
# Initialise Superset's metadata DB and admin user, then start the web server.
set -euo pipefail
superset db upgrade
superset fab create-admin \
    --username "${SUPERSET_ADMIN_USER:-admin}" --password "${SUPERSET_ADMIN_PASSWORD:-admin}" \
    --firstname Admin --lastname User --email admin@example.com || true
superset init
exec /usr/bin/run-server.sh
