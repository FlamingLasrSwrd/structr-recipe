#!/usr/bin/env bash
# Build a Structr instance from nothing and check it against the golden snapshot.
#
#   tools/rebuild.sh
#
# Waits for Structr, runs every script in scripts/ in build order (stopping at the first
# failure and showing the tail of its log), then diffs the resulting graph and schema against
# tools/expected_state.json. Prints SNAPSHOT IDENTICAL and exits 0 only if all of that held.
# It does not start or stop containers: bring the stack up first (cloud/bootstrap.sh).
#
# Environment (all optional):
#   STRUCTR_URL      instance to build (default http://localhost:8083)
#   STRUCTR_SUPERUSER_PASSWORD   read from the environment, else from .env
#   PYTHON           interpreter (default python3)
#   WAIT_S           seconds to wait for Structr (default 300)
#   LOG_DIR          where each script's output goes (default ${TMPDIR:-/tmp}/structr-rebuild-logs)
#   SCRIPTS_GLOB     which scripts to run (default scripts/*.py); a partial run still diffs
#   DRY_RUN=1        print the scripts that would run, in order, and stop
#   SKIP_SNAPSHOT=1  do not diff at the end
#
# WARNING: script 15a resets the instance's data. Point this at a disposable instance, or at
# one you are content to rebuild from the scripts (which is every instance in this project).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here" || exit 1
if [ -z "${STRUCTR_SUPERUSER_PASSWORD:-}" ] && [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${STRUCTR_SUPERUSER_PASSWORD:?set STRUCTR_SUPERUSER_PASSWORD, or create .env (cloud/bootstrap.sh --env-only does)}"
export STRUCTR_SUPERUSER_PASSWORD
export STRUCTR_URL="${STRUCTR_URL:-http://localhost:8083}"
py="${PYTHON:-python3}"
glob="${SCRIPTS_GLOB:-scripts/*.py}"
logdir="${LOG_DIR:-${TMPDIR:-/tmp}/structr-rebuild-logs}"

# shellcheck disable=SC2086   # the glob is meant to expand
scripts=$(ls $glob 2>/dev/null | sort -V)
if [ -z "$scripts" ]; then echo "no scripts match $glob" >&2; exit 1; fi
if [ "${DRY_RUN:-}" = "1" ]; then echo "$scripts"; exit 0; fi

mkdir -p "$logdir"
bash tools/wait_for_structr.sh "${WAIT_S:-300}" || exit 1
start=$(date +%s)
count=0
for f in $scripts; do
  echo "== $f"
  log="$logdir/$(basename "$f").log"
  if ! "$py" "$f" >"$log" 2>&1; then
    echo "FAILED at $f (full log: $log)"
    tail -25 "$log"
    exit 1
  fi
  count=$((count + 1))
done
echo "all $count scripts ran in $(( $(date +%s) - start )) s (logs in $logdir)"

if [ "${SKIP_SNAPSHOT:-}" = "1" ]; then exit 0; fi
if "$py" tools/snapshot_state.py | diff - tools/expected_state.json; then
  echo "SNAPSHOT IDENTICAL"
else
  echo "SNAPSHOT DIFFERS from tools/expected_state.json (diff above)" >&2
  exit 1
fi
