#!/usr/bin/env bash
# Wait until a Structr instance is ready to serve requests.
#
#   tools/wait_for_structr.sh [timeout_seconds]        (default 300)
#
# Reads STRUCTR_URL (default http://localhost:8083). Polls /structr/health/ready, which needs no
# credentials (503 while Structr starts, stops or deploys; the compose health check reads it too).
# It used to poll the schema endpoint with the superuser's password, so a wrong password in .env
# was retried every 3 s, and on Structr 7.1 three wrong superuser passwords in 15 minutes block the
# superuser everywhere. The password is now proven by the first request a tool makes, as the tools'
# own account (mealplanner/connection.py), which stops at a 401 instead of retrying.
# Exits 0 once Structr answers 200, 1 on timeout. A first boot takes a minute or two; a cold
# machine longer.
set -u
url="${STRUCTR_URL:-http://localhost:8083}"
timeout="${1:-300}"
start=$(date +%s)
code=""
while :; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url/structr/health/ready" || true)
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
