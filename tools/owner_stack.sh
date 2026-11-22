#!/usr/bin/env bash
# The stack that holds the owner's own data: its own compose project and volumes, on its own
# port, so nothing done to the development stack or a throwaway one can reach it.
#
#   tools/owner_stack.sh build   first time only: start it, run the full build, then
#                                tools/make_owner_instance.py (removes demos, marks it the owner's)
#   tools/owner_stack.sh up      start it and wait until it answers; refuses a Structr image other than the one
#                                it last ran unless UPGRADE=1 (tools/image_guard.sh: Structr upgrades its database)
#   tools/owner_stack.sh stop    stop it, backing it up as it stops (tools/backup.py; NO_BACKUP=1 skips the
#                                backup); the data stays in its volumes
#   tools/owner_stack.sh url     print the STRUCTR_URL to use with tools/import_recipe.py
#
# Never `docker compose -p mealplanner-owner down -v`: -v deletes the volumes, which hold the
# data, and nothing in the repository can rebuild it. On an 8 GB laptop run one stack at a time;
# `build` refuses while another Structr stack is running.
#
# `up` also serves HTTPS on port 8443 once tools/make_https_cert.py has made private/https/
# (docs/pages.md, "HTTPS"). It then names its compose files, so a docker-compose.override.yml is not read.
#
# Optional: OWNER_PORT (default 8085), STRUCTR_HTTPS_PORT (default 8443).
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"
project=mealplanner-owner
port="${OWNER_PORT:-8085}"
url="http://localhost:$port"

https_files=()
compose() { STRUCTR_PORT="$port" docker compose -p "$project" ${https_files[@]+"${https_files[@]}"} "$@"; }
use_https() {
  [ -e private/https ] || return 0
  # Structr told to serve HTTPS from a keystore it cannot read may not start at all, HTTP included
  if [ ! -f private/https/keystore.p12 ] || [ ! -f private/https/structr.env ]; then
    echo "private/https is incomplete: run tools/make_https_cert.py again, or move that folder away to serve HTTP only." >&2
    exit 1
  fi
  https_files=(-f docker-compose.yml -f docker-compose.https.yml)
  if [ -f private/https/ca.crt ] && ! openssl x509 -in private/https/ca.crt -noout -checkend $((35 * 86400)) >/dev/null 2>&1; then
    echo "warning: the HTTPS certificate expires within a month; tools/make_https_cert.py --force makes another (docs/pages.md)." >&2
  fi
}
load_env() {
  if { [ -z "${STRUCTR_SUPERUSER_PASSWORD:-}" ] || [ -z "${STRUCTR_TOOLS_PASSWORD:-}" ]; } && [ -f .env ]; then
    set -a; . ./.env; set +a
  fi
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
    use_https
    bash tools/image_guard.sh "$project-structr-1"    # a changed Structr image upgrades the data: only when asked
    compose up -d
    bash tools/wait_for_structr.sh "${WAIT_S:-300}"
    echo "export STRUCTR_URL=$url"
    if [ "${#https_files[@]}" -gt 0 ]; then
      echo "other devices: https://<this computer's address>:${STRUCTR_HTTPS_PORT:-8443}/structr/html/login"
    fi
    ;;
  stop)
    if [ -n "${NO_BACKUP:-}" ]; then
      compose stop
    elif ! python3 tools/backup.py now --leave-stopped; then
      echo "The backup failed (above); the stack is stopped anyway." >&2
      compose stop
      exit 1
    fi
    ;;
  url)
    echo "$url"
    ;;
  *)
    sed -n '2,20p' "$0"
    exit 2
    ;;
esac
