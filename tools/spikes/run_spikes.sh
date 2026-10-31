#!/usr/bin/env bash
# Run the Structr feature spikes (tools/spikes/structr_feature_spikes.py) on a throwaway stack.
#
#   bash tools/spikes/run_spikes.sh [results.json]      (default tools/spikes/last_results.json)
#
# Starts its own compose project (structr-spike, port 8084) with the settings some spikes need
# (docker-compose.spike.yml), runs the spikes' setup, restarts Structr so no check runs straight
# after the schema changes (hard rule 8), runs verify, and destroys the stack and its volumes
# (KEEP=1 leaves it up). ONLY=format,doas runs only those spikes. It refuses to start while
# another Structr stack runs: one stack at a time.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$here"
set -a; . ./.env; set +a
project=structr-spike
port=${SPIKE_PORT:-8084}
out="${1:-tools/spikes/last_results.json}"
compose=(docker compose -p "$project" -f docker-compose.yml -f tools/spikes/docker-compose.spike.yml)
if docker ps --format '{{.Names}}' | grep -q structr; then
  echo "another Structr stack is running: stop it first (one stack at a time)" >&2
  docker ps --format '  {{.Names}}' >&2
  exit 1
fi
free -m | sed -n 2p
STRUCTR_PORT=$port "${compose[@]}" up -d 2>&1 | tail -2
if [ "${KEEP:-}" != "1" ]; then
  trap 'STRUCTR_PORT=$port "${compose[@]}" down -v 2>&1 | tail -1' EXIT
fi
SPIKE_USER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
export STRUCTR_URL="http://localhost:$port" SPIKE_COMPOSE_PROJECT="$project" SPIKE_USER_PASSWORD
bash tools/wait_for_structr.sh 300
python3 tools/create_tools_user.py      # connect() logs in as it; the spikes' own requests stay the superuser's
only=(); [ -n "${ONLY:-}" ] && only=(--only "$ONLY")
python3 tools/spikes/structr_feature_spikes.py setup "${only[@]}"
STRUCTR_PORT=$port "${compose[@]}" restart structr 2>&1 | tail -1
bash tools/wait_for_structr.sh 300
python3 tools/spikes/structr_feature_spikes.py verify --json "$out" "${only[@]}"
