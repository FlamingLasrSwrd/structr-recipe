#!/usr/bin/env bash
# Bring up this project's Structr + Neo4j stack in a fresh environment: a Claude cloud
# session, a new server, or a laptop. Safe to re-run.
#
#   cloud/bootstrap.sh [--env-only] [--build]
#
#   --env-only   only make sure .env (the three passwords) exists, and stop
#   --build      once the stack answers, run tools/rebuild.sh (every script, then the snapshot check)
#
# Passwords: taken from NEO4J_PASSWORD / STRUCTR_SUPERUSER_PASSWORD / STRUCTR_TOOLS_PASSWORD if
# set (a cloud environment provides them as variables), otherwise generated at random. The third
# is the tools' own account (tools/create_tools_user.py). An existing .env is never overwritten:
# a password it lacks is added at its end, and nothing in it is changed. The database this
# creates is DISPOSABLE: everything in it is rebuilt from the committed scripts, so a throwaway
# password is right. Do not reuse a real one.
#
# Optional: STRUCTR_PORT (default 8083), COMPOSE_PROJECT_NAME (to run a second stack).
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

env_only=0; build=0
for arg in "$@"; do
  case "$arg" in
    --env-only) env_only=1 ;;
    --build) build=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

generate() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 16
  else head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

if [ -f .env ]; then
  if grep -q '^STRUCTR_TOOLS_PASSWORD=' .env; then
    echo ".env already exists; leaving it alone"
  else
    printf 'STRUCTR_TOOLS_PASSWORD=%s\n' "${STRUCTR_TOOLS_PASSWORD:-$(generate)}" >> .env
    echo ".env already exists; added STRUCTR_TOOLS_PASSWORD to it (value not shown), changed nothing else"
  fi
else
  neo="${NEO4J_PASSWORD:-$(generate)}"
  structr="${STRUCTR_SUPERUSER_PASSWORD:-$(generate)}"
  tools="${STRUCTR_TOOLS_PASSWORD:-$(generate)}"
  ( umask 077; printf 'NEO4J_PASSWORD=%s\nSTRUCTR_SUPERUSER_PASSWORD=%s\nSTRUCTR_TOOLS_PASSWORD=%s\n' "$neo" "$structr" "$tools" > .env )
  src="generated"
  if [ -n "${NEO4J_PASSWORD:-}" ] && [ -n "${STRUCTR_SUPERUSER_PASSWORD:-}" ] && [ -n "${STRUCTR_TOOLS_PASSWORD:-}" ]; then
    src="taken from the environment"
  fi
  echo "created .env ($src; values not shown)"
fi
if [ "$env_only" = "1" ]; then exit 0; fi

command -v docker >/dev/null 2>&1 || { echo "docker is not installed" >&2; exit 1; }
if ! docker info >/dev/null 2>&1; then
  echo "the Docker daemon is not answering; trying to start it" >&2
  (service docker start >/dev/null 2>&1 || true)
  sleep "${DOCKER_START_WAIT_S:-5}"
  # In a Claude cloud session the init script fails ("ulimit: error setting limit"), and so does a
  # session restored after its container restarted; the daemon itself starts fine (2026-10-31).
  if ! docker info >/dev/null 2>&1 && command -v dockerd >/dev/null 2>&1; then
    log="${TMPDIR:-/tmp}/dockerd.log"
    echo "service docker start did not start it; starting dockerd directly (its log: $log)" >&2
    nohup dockerd >"$log" 2>&1 &
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  fi
  docker info >/dev/null 2>&1 || { echo "Docker daemon still not answering" >&2; exit 1; }
fi

# Pull what is missing, retrying: Docker Hub answers "429 Too Many Requests" to an anonymous pull now
# and then (three times in one session, 2026-10-31), and compose gives up at the first. An image
# already here is not asked for again.
pull() {
  local image="$1" try wait="${PULL_RETRY_BASE_S:-15}"
  for try in 1 2 3 4 5; do
    if docker pull -q "$image" >/dev/null 2>&1; then return 0; fi
    if [ "$try" -lt 5 ]; then
      echo "pulling $image failed (try $try of 5); trying again in ${wait} s" >&2
      sleep "$wait"; wait=$((wait * 2))
    fi
  done
  echo "could not pull $image" >&2
  return 1
}
for image in $(docker compose config --images); do
  docker image inspect "$image" >/dev/null 2>&1 || pull "$image" || exit 1
done

echo "starting the stack (first start pulls images and boots Structr: a minute or two)"
docker compose up -d
bash tools/wait_for_structr.sh "${WAIT_S:-300}"
echo "stack is up at ${STRUCTR_URL:-http://localhost:${STRUCTR_PORT:-8083}}"

if [ "$build" = "1" ]; then
  exec bash tools/rebuild.sh
fi
echo "next: bash tools/rebuild.sh   (makes the tools' account, builds everything from the scripts and checks the snapshot)"
