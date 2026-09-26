#!/usr/bin/env bash
# Start/stop a Cloudflare Tunnel exposing this instance's Structr (default
# http://localhost:8083) to the public hostname and Access policy configured
# in the Cloudflare Zero Trust dashboard for this tunnel's token. Manual,
# on purpose: this project's stance is "public only while someone is
# actually working" -- run `start` when you sit down, `stop` when you don't
# need external access, same as bringing the stack up/down with bootstrap.sh.
#
#   tools/tunnel.sh start    # install cloudflared if missing, run the tunnel
#   tools/tunnel.sh stop     # stop it
#   tools/tunnel.sh status   # running or not, and the tail of its log
#
# Needs CLOUDFLARE_TUNNEL_TOKEN (from the environment, or .env). Optional:
# TUNNEL_PID_FILE / TUNNEL_LOG_FILE to relocate its bookkeeping (default
# $TMPDIR/structr-recipe-cloudflared.{pid,log}) -- a second checkout running
# its own tunnel, or a test, would otherwise collide with a real one's files. Get one from
# the Cloudflare Zero Trust dashboard: Networks > Tunnels > Create a tunnel >
# Cloudflared connector -- it hands you a `cloudflared tunnel run --token ...`
# command; the token is the long string after --token. The dashboard is also
# where you set the Public Hostname (which path/port it points at -- use this
# machine's localhost:8083) and the Access policy (who's allowed in): none of
# that lives in this repo, because it's account/domain configuration, not
# instance state. See CLOUD.md "Public access via Cloudflare Tunnel" for the
# walkthrough.
#
# cloudflared itself is installed from Cloudflare's own apt repo (not
# GitHub), the first time `start` needs it and doesn't find it. The daemon
# is started detached with setsid so it survives past this script's own
# shell -- the same fix cloud/bootstrap.sh needed for dockerd, and for the
# same reason (a plain `nohup ... &` here died as soon as the shell that
# started it exited).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] && [ -f "$here/.env" ]; then
  set -a; . "$here/.env"; set +a
fi

pid_file="${TUNNEL_PID_FILE:-${TMPDIR:-/tmp}/structr-recipe-cloudflared.pid}"
log_file="${TUNNEL_LOG_FILE:-${TMPDIR:-/tmp}/structr-recipe-cloudflared.log}"

install_cloudflared() {
  command -v cloudflared >/dev/null 2>&1 && return 0
  echo "cloudflared not found; installing from Cloudflare's apt repo..." >&2
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "no apt-get here -- install cloudflared yourself (https://pkg.cloudflare.com/index.html) and re-run" >&2
    return 1
  fi
  (
    set -e
    mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
      > /etc/apt/sources.list.d/cloudflared.list
    apt-get update -qq
    apt-get install -qq -y cloudflared
  ) || { echo "cloudflared install failed" >&2; return 1; }
}

is_running() {
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

cmd="${1:-}"
case "$cmd" in
  start)
    if is_running; then
      echo "already running (pid $(cat "$pid_file")); see: tools/tunnel.sh status"
      exit 0
    fi
    : "${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN (from the Zero Trust dashboard), or add it to .env}"
    install_cloudflared || exit 1
    # --no-autoupdate is a `tunnel` flag, not a `run` one -- `tunnel run --no-autoupdate`
    # fails with "flag provided but not defined" (confirmed against 2026.9.3); it must
    # come before `run`. Skips needing update.cloudflareclient.com reachable too.
    setsid nohup cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" \
      >"$log_file" 2>&1 </dev/null &
    echo "$!" > "$pid_file"
    sleep 3
    if is_running; then
      echo "started (pid $(cat "$pid_file")), log: $log_file"
      echo "check its Public Hostname + Access policy in the Zero Trust dashboard for where it's reachable"
    else
      echo "cloudflared exited immediately -- see $log_file" >&2
      tail -20 "$log_file" >&2
      rm -f "$pid_file"
      exit 1
    fi
    ;;
  stop)
    if ! is_running; then
      echo "not running"
      rm -f "$pid_file"
      exit 0
    fi
    kill "$(cat "$pid_file")"
    rm -f "$pid_file"
    echo "stopped"
    ;;
  status)
    if is_running; then
      echo "running (pid $(cat "$pid_file"))"
      if [ -f "$log_file" ]; then
        tail -10 "$log_file"
      fi
    else
      echo "not running"
    fi
    ;;
  *)
    echo "usage: tools/tunnel.sh {start|stop|status}" >&2
    exit 2
    ;;
esac
