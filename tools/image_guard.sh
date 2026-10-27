#!/usr/bin/env bash
# Refuse to start a stack's Structr on another image than the one it last ran, unless UPGRADE=1.
#
#   bash tools/image_guard.sh <structr container name>
#
# Structr upgrades its database when it starts on a newer version (7.1: application.migration.mode,
# apply by default), and nothing but a backup undoes that. tools/owner_stack.sh up runs this first,
# so a changed image line in docker-compose.yml never upgrades the owner's instance unasked. Exits 0
# when the container does not exist yet, runs the image docker-compose.yml names, or UPGRADE=1 is set.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container="${1:?name the Structr container}"
wanted="$(sed -n 's#^ *image: *\(structr/structr:[^ ]*\) *$#\1#p' "$here/docker-compose.yml" | head -1)"
current="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
if [ -z "$current" ] || [ "$current" = "$wanted" ] || [ "${UPGRADE:-}" = "1" ]; then
  exit 0
fi
cat >&2 <<EOF
$container last ran $current; docker-compose.yml now names $wanted.
Starting it on $wanted upgrades its database, and only a backup undoes that. First:
  python3 tools/backup.py now                     (with the stack stopped: a backup of it as it is)
then, if you want to see first what the upgrade would change (Structr writes it to its log and does
not start, so the wait below ends in a time-out):
  STRUCTR_MIGRATION_MODE=dry-run UPGRADE=1 bash tools/owner_stack.sh up
  docker logs $container 2>&1 | grep MigrationService
and to upgrade:
  UPGRADE=1 bash tools/owner_stack.sh up
EOF
exit 1
