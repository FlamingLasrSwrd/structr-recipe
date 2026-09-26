#!/usr/bin/env bash
# Bring up this project's Structr + Neo4j stack in a fresh environment: a Claude cloud
# session, a new server, or a laptop. Safe to re-run.
#
#   cloud/bootstrap.sh [--env-only] [--build]
#
#   --env-only   only make sure .env (the two passwords) exists, and stop
#   --build      once the stack answers, run tools/rebuild.sh (every script, then the snapshot check)
#
# Passwords: taken from NEO4J_PASSWORD / STRUCTR_SUPERUSER_PASSWORD if set (a cloud environment
# provides them as variables), otherwise generated at random. An existing .env is never
# overwritten. The database this creates is DISPOSABLE: everything in it is rebuilt from the
# committed scripts, so a throwaway password is right. Do not reuse a real one.
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
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

generate() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 16
  else head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

if [ -f .env ]; then
  echo ".env already exists; leaving it alone"
else
  neo="${NEO4J_PASSWORD:-$(generate)}"
  structr="${STRUCTR_SUPERUSER_PASSWORD:-$(generate)}"
  ( umask 077; printf 'NEO4J_PASSWORD=%s\nSTRUCTR_SUPERUSER_PASSWORD=%s\n' "$neo" "$structr" > .env )
  src="generated"
  if [ -n "${NEO4J_PASSWORD:-}" ] && [ -n "${STRUCTR_SUPERUSER_PASSWORD:-}" ]; then src="taken from the environment"; fi
  echo "created .env ($src; values not shown)"
fi
if [ "$env_only" = "1" ]; then exit 0; fi

command -v docker >/dev/null 2>&1 || { echo "docker is not installed" >&2; exit 1; }
if ! docker info >/dev/null 2>&1; then
  echo "the Docker daemon is not answering; trying to start it" >&2
  (service docker start >/dev/null 2>&1 || true)
  sleep 5
  docker info >/dev/null 2>&1 || { echo "Docker daemon still not answering" >&2; exit 1; }
fi

echo "starting the stack (first start pulls images and boots Structr: a minute or two)"
docker compose up -d
bash tools/wait_for_structr.sh "${WAIT_S:-300}"
echo "stack is up at ${STRUCTR_URL:-http://localhost:${STRUCTR_PORT:-8083}}"

if [ "$build" = "1" ]; then
  exec bash tools/rebuild.sh
fi
echo "next: bash tools/rebuild.sh   (builds everything from the scripts and checks the snapshot)"
