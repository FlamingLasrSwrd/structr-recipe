#!/usr/bin/env bash
# Wait until a Structr instance answers on its schema endpoint.
#
#   tools/wait_for_structr.sh [timeout_seconds]        (default 300)
#
# Reads STRUCTR_URL (default http://localhost:8083) and STRUCTR_SUPERUSER_PASSWORD from the
# environment, falling back to .env in the repo root. Exits 0 once Structr answers 200, 1 on
# timeout. A first boot takes a minute or two; a cold machine longer.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${STRUCTR_SUPERUSER_PASSWORD:-}" ] && [ -f "$here/.env" ]; then
  set -a; . "$here/.env"; set +a
fi
: "${STRUCTR_SUPERUSER_PASSWORD:?set STRUCTR_SUPERUSER_PASSWORD, or create .env (cloud/bootstrap.sh --env-only does)}"
url="${STRUCTR_URL:-http://localhost:8083}"
timeout="${1:-300}"
start=$(date +%s)
code=""
while :; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    -H "X-User: superadmin" -H "X-Password: $STRUCTR_SUPERUSER_PASSWORD" "$url/structr/rest/SchemaNode" || true)
  if [ "$code" = "200" ]; then
    echo "Structr answered at $url after $(( $(date +%s) - start )) s"
    exit 0
  fi
  if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
    echo "Structr did not answer at $url within ${timeout}s (last HTTP status: ${code:-none})" >&2
    exit 1
  fi
  sleep 3
done
