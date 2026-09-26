# Working on this project in Claude Code's cloud

Why: the stack (Structr and Neo4j, two JVMs) plus the desktop app do not fit comfortably in 8 GB
of laptop RAM. A cloud session runs on an Anthropic-managed VM (about 4 vCPUs, 16 GB RAM, x86
Ubuntu 24.04, Docker and `docker compose` installed; the writable disk behaves as roughly 30 GB
free, not the whole disk `df` reports), keeps running when you close the laptop, and costs nothing
beyond your plan's usage limits. This guide is written from the
[cloud docs](https://code.claude.com/docs/en/claude-code-on-the-web) and
[environment docs](https://code.claude.com/docs/en/cloud-environments). **The smoke test below has
now been run once** (2026-09-26); its section says what held and what needed a fix.

## What this repository already gives a cloud session

| File | Job |
|---|---|
| `CLAUDE.md` | your working agreements and commands, since a cloud session has none of your local memory |
| `cloud/setup.sh` | the environment's setup script: `requests`, OR-tools in its own venv, the two Docker images |
| `cloud/bootstrap.sh` | brings the stack up: makes `.env`, `docker compose up -d`, waits until Structr answers |
| `tools/rebuild.sh` | builds an instance from nothing (every script) and checks the snapshot |
| `tools/wait_for_structr.sh` | the readiness check both use |

Everything the database holds is rebuilt from committed scripts, which is what makes a disposable
cloud database fine: nothing in it is precious.

## One-time setup (about ten minutes, by hand)

1. **Push everything.** A cloud session clones from GitHub, not from your laptop. `git status` clean
   and `git log origin/main..` empty means it will see what you see.
2. **Connect GitHub** at [claude.ai/code](https://claude.ai/code). Either install the Claude GitHub App
   on `FlamingLasrSwrd/structr-recipe` during onboarding, or run `/web-setup` in a terminal to send
   your `gh` token. A public repository can be cloned either way; pushing a branch needs the
   connection to have access.
3. **Create an environment** (the settings dialog at claude.ai/code):
   - *Name:* `structr-recipe`.
   - *Network access:* **Trusted** (the default). It allows Docker Hub, where both images live, and PyPI.
   - *Environment variables:* `NEO4J_PASSWORD` and `STRUCTR_SUPERUSER_PASSWORD`. Use two new random
     strings (`openssl rand -hex 16`), **not** passwords you use anywhere else: anyone who can use the
     environment can read them, and the database they protect is disposable.
   - *Setup script:* paste the contents of `cloud/setup.sh`.
4. **Start a session.** In the desktop app choose **Cloud** instead of **Local** when you start it,
   then pick the repository and this environment. From a terminal in the repo:
   `claude --cloud "your task"`. From your phone: the Code tab of the Claude app.
5. **Make the first session the smoke test** below. It costs a few minutes and tells you whether
   every assumption in this file holds.

### The first prompt (smoke test)

> Read CLAUDE.md and CLOUD.md. Then, reporting each result and how long it took: (1) run the offline
> tests on both interpreters (`python3 -m unittest discover -s tests -t .` and
> `/opt/solver-venv/bin/python -m unittest discover -s tests -t .`) and `python3 tools/check_names.py`;
> (2) run `bash cloud/bootstrap.sh` and tell me whether Docker started and Structr answered;
> (3) run `bash tools/rebuild.sh` in the background, poll its log, and tell me the final line
> (I expect `SNAPSHOT IDENTICAL`); (4) list anything that did not match CLOUD.md. Do not commit or
> push anything.

What to expect, now measured in an actual cloud VM (2026-09-26): the offline suite takes 14-17 s per
interpreter; a Structr boot takes 24-74 s (faster once the images are pulled); the rebuild of all 48
scripts took 209 s. All comfortably inside the laptop-derived estimates this file used to give.

## Day to day

- **Each new session starts with no running stack and no data.** For offline work (tests, the planner,
  documents) that does not matter. For anything against Structr, ask for `bash cloud/bootstrap.sh`
  and then `bash tools/rebuild.sh`. A session that sits idle is reclaimed, and a rebuild running in
  the background at that moment is lost; start it again.
- **Results arrive as a branch.** Cloud sessions push a branch and can open a pull request from
  claude.ai/code; you review and merge. `CLAUDE.md`'s working agreements say when a session commits
  and pushes on its own (changed 2026-09-26: no longer waits for a yes on each batch, to stop
  fighting the stop hook that blocks ending a turn on unpushed work). To continue a cloud session on
  your laptop: `claude --teleport` from a checkout of the repository (it asks you to stash
  uncommitted changes first).
- **The documents live only in `docs/`.** Decided 2026-09-26: there is one copy, in git, so a cloud
  session and a laptop session see the same thing and the repository is the whole project. The
  Obsidian vault copy is frozen and must not be edited. To keep using Obsidian, open the repository's
  `docs/` folder as a vault (Obsidian can open any folder), so edits land in git directly.
- **Free your laptop's RAM** whenever you are not using it: `docker compose stop` (the data volumes are
  kept), and `docker compose up -d` when you want it back.

## What does not carry over

Your local Claude memory (the working agreements are in `CLAUDE.md` for that reason); a running database (the cache keeps files, not processes); the laptop's `.venv`; `.env`
(never uploaded, by design); anything the desktop app gives a local session that is not in the repo,
such as its in-app browser tools.

## Security

- The repository is public; the environment's variables are not, but any user of the environment
  can read them. Two throwaway values, as above.
- The stack's ports stay inside the VM **unless `tools/tunnel.sh start` is running** (below) — stop
  it when you're not actively using it.
- Do not paste a real credential into a cloud session: its transcript is stored on claude.ai, and
  a shared session shows what it contains.
- Keep sessions Private unless you mean to share one.

## Public access via Cloudflare Tunnel

🛑 **Verified 2026-09-26: `cloudflared` cannot actually connect from inside a Claude Code cloud
session, no matter what the network policy allows.** It installs and starts fine, and reaches
`api.cloudflare.com` over ordinary HTTPS fine, but its tunnel/edge connection (both the QUIC and
the HTTP/2 fallback) needs outbound access to `region1.v2.argotunnel.com`/`region2.v2.argotunnel.com`
on **port 7844**, and it dials that directly rather than through this session's HTTP CONNECT proxy —
confirmed by `curl`'s own CONNECT to the same host:port succeeding while `cloudflared` still times
out with "no recent network activity" / "HTTP/2 connection is blocked or unreachable". None of
`cloudflared`'s `--proxy-*` flags apply here; every one of them is documented as configuring the
*origin* side (how it reaches Structr locally), not how it reaches Cloudflare. This is a structural
property of the sandbox (an HTTP CONNECT-only egress proxy, no direct internet route for a
hand-rolled Go dialer to fall back to), not something a network-policy change or a cloudflared flag
fixes.

**What this means in practice:** the account-side setup below (the tunnel, its Public Hostname, its
Access policy) is real, reusable configuration — do it once, and it works unchanged from anywhere
with ordinary internet access: a Hetzner box (see "If cloud sessions do not suit"), your laptop, any
machine that isn't behind a CONNECT-only proxy. It just can't be the *cloud session itself* running
`cloudflared`. For visual testing from inside a cloud session today, take a screenshot with headless
Chromium against `localhost` instead (it's pre-installed; `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`)
and have the session send you the image — no outbound connection needed at all.

`tools/tunnel.sh` starts/stops
[`cloudflared`](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/),
which makes an *outbound* connection to Cloudflare — nothing ever listens on a public port on
whatever host runs it, so there's no port to forget to close. Put an
[Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) policy in front of it
(a login, e.g. an email one-time code) and it's safe to leave configured between sessions even
though the tunnel process itself is started/stopped manually, same as the stack.

**One-time setup, in the Cloudflare dashboard** (needs a domain on Cloudflare — the free plan is
enough; add one first at [dash.cloudflare.com](https://dash.cloudflare.com) if you don't have one):

1. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared connector.** Name it (e.g.
   `structr-recipe`). It gives you a `cloudflared tunnel run --token eyJhbG...` command — the long
   string after `--token` is what this script needs.
2. **Public Hostname**, on the same tunnel: a subdomain of your Cloudflare domain (e.g.
   `structr.yourdomain.com`), pointed at `http://localhost:8083` — that's this VM's own Structr
   port, resolved from inside the tunnel, not a URL you have to make reachable yourself.
3. **Access → Applications → Add an application → Self-hosted**, same hostname, with a policy
   restricted to your own email (or however you want to gate it). This is the part that makes it
   actually safe: anyone who finds the URL still has to pass Cloudflare's login first, not
   Structr's own.
4. Put the token from step 1 in this environment's variables or in `.env` as
   `CLOUDFLARE_TUNNEL_TOKEN` (see `.env.example`).

None of steps 1-3 live in this repo — they're account/domain configuration, done once, in your
Cloudflare account, not instance state a script could reproduce.

**Every session after that:**

```bash
tools/tunnel.sh start     # installs cloudflared if missing, starts the tunnel
tools/tunnel.sh status    # running or not, tail of its log
tools/tunnel.sh stop      # when you're done -- the public hostname goes with it
```

The environment's own network policy has to allow `pkg.cloudflare.com` (installing `cloudflared`
itself) at minimum, and ideally `*.cloudflare.com`/`*.cfargotunnel.com`/`*.argotunnel.com` for the
rest — edit Network access in the environment's settings if `tools/tunnel.sh start` can't reach
them. That alone is not sufficient for the tunnel to actually connect *from a cloud session*, per
the finding above; it's still worth doing so `tools/tunnel.sh status` gives an accurate error
instead of a generic timeout, and so the same environment variables carry over cleanly if you ever
run this project somewhere the tunnel can connect.

**Later, opening it to anyone** (not needed yet): remove the Access policy from step 3. The
tunnel and hostname don't change.

## Limits

- Cloud sessions share your account's rate limits; several in parallel use them up faster.
- The VM's ceilings are approximate (4 vCPUs, 16 GB RAM, ~30 GB of writable disk); the images and a
  built instance are a few GB, so there is room.
- The setup script's result is cached only if it finishes in about five minutes, and the cache is
  rebuilt when the script or the network settings change and after roughly a week.
- A command Claude runs waits two minutes by default (up to ten if asked) before moving to the background.

## First-run checklist: verified 2026-09-26

The smoke test above has now run in an actual cloud VM. Results against the original checklist:

1. **`service docker start` does not work here.** Its init script calls `ulimit`, which the sandbox
   refuses ("Operation not permitted"), so it exits without starting the daemon. Both `cloud/setup.sh`
   and `cloud/bootstrap.sh` now fall back to running `dockerd` directly, waiting up to 30 s for it to
   answer. **The fallback must detach with `setsid` and closed stdin** (`setsid nohup dockerd
   >"$dlog" 2>&1 </dev/null &`); a plain `nohup dockerd & ` was killed as soon as the shell that
   started it ended, which in this harness is after every command. With `setsid` the daemon survived
   across separate tool calls and `docker compose up -d` worked. `docker compose` itself needed no
   fallback.
2. **Not confirmed — the environment's Setup script field was empty for this session.** `setup.sh`
   was instead run by hand and finished in 17 s (well inside five minutes) and exited 0. Paste it
   into the environment's Setup script field so a fresh session gets it automatically; until then,
   run it by hand once per session before `bootstrap.sh`.
3. **Confirmed.** `requests` installs, `/opt/solver-venv` builds (`python3 -m venv` worked; the
   `--without-pip` fallback was not needed), and all 9 solver-only tests pass under it.
4. **Confirmed.** Structr answered well inside the 300 s default (24-74 s measured).
5. **Confirmed.** `tools/rebuild.sh` printed `SNAPSHOT IDENTICAL`, and the data survived multiple
   Docker daemon restarts within the same session (item 1's testing restarted it three times).
6. **Not exercised.** This session was told not to push; branch-push and `main`-push permissions
   are still unconfirmed.
7. **Not confirmed — `NEO4J_PASSWORD` and `STRUCTR_SUPERUSER_PASSWORD` were not set** in this
   session's environment, so `bootstrap.sh` took its documented fallback and generated throwaway
   passwords instead. Set the two variables in the environment (step 3 of one-time setup) if you want
   the same passwords every session; unset is safe, just not what this file originally assumed.

## If cloud sessions do not suit

The reason to leave them would be needing the database to persist between sessions. The alternative
is a small server: Hetzner's CX33 (4 vCPUs, 8 GB) was 8.49 euros a month plus VAT in June 2026. The
same `cloud/bootstrap.sh` and `tools/rebuild.sh` work on it unchanged, with Claude Code installed on
the server and used over SSH. Keep Structr's port off the public internet (SSH tunnel or a VPN).
