#!/usr/bin/env bash
# The stack that holds the owner's own data: its own compose project and volumes, on its own
# port, so nothing done to the development stack or a throwaway one can reach it.
#
#   tools/owner_stack.sh build   first time only: start it, run the full build, then
#                                tools/make_owner_instance.py (removes demos, marks it the owner's)
#   tools/owner_stack.sh up      start it and wait until it answers
#   tools/owner_stack.sh stop    stop it; the data stays in its volumes
#   tools/owner_stack.sh url     print the STRUCTR_URL to use with tools/import_recipe.py
#
# Never `docker compose -p mealplanner-owner down -v`: -v deletes the volumes, which hold the
# data, and nothing in the repository can rebuild it. On an 8 GB laptop run one stack at a time;
# `build` refuses while another Structr stack is running.
#
# Optional: OWNER_PORT (default 8085).
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"
project=mealplanner-owner
port="${OWNER_PORT:-8085}"
url="http://localhost:$port"

compose() { STRUCTR_PORT="$port" docker compose -p "$project" "$@"; }
load_env() {
  if [ -z "${STRUCTR_SUPERUSER_PASSWORD:-}" ] && [ -f .env ]; then set -a; . ./.env; set +a; fi
  : "${STRUCTR_SUPERUSER_PASSWORD:?set STRUCTR_SUPERUSER_PASSWORD, or create .env}"
  export STRUCTR_SUPERUSER_PASSWORD STRUCTR_URL="$url"
}

case "${1:-}" in
  build)
    others="$(docker ps --format '{{.Names}}' | grep -v "^$project-" | grep -i -e structr -e neo4j || true)"
    if [ -n "$others" ]; then
      echo "Another stack is running ($(echo "$others" | tr '\n' ' ')). Stop it first: two stacks do not fit in 8 GB." >&2
      exit 1
    fi
    load_env
    compose up -d
    bash tools/rebuild.sh
    python3 tools/make_owner_instance.py
    echo "Built. Use it with: export STRUCTR_URL=$url"
    ;;
  up)
    load_env
    compose up -d
    bash tools/wait_for_structr.sh "${WAIT_S:-300}"
    echo "export STRUCTR_URL=$url"
    ;;
  stop)
    compose stop
    ;;
  url)
    echo "$url"
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 2
    ;;
esac
