# Working on this project in Claude Code's cloud

Why: the stack (Structr and Neo4j, two JVMs) plus the desktop app do not fit comfortably in 8 GB
of laptop RAM. A cloud session runs on an Anthropic-managed VM (about 4 vCPUs, 16 GB RAM, 30 GB
disk, x86 Ubuntu 24.04, Docker and `docker compose` installed), keeps running when you close the
laptop, and costs nothing beyond your plan's usage limits. This guide is written from the
[cloud docs](https://code.claude.com/docs/en/claude-code-on-the-web) and
[environment docs](https://code.claude.com/docs/en/cloud-environments). **Nothing here has been run
in a cloud session yet**: the last section lists exactly what the first session must confirm.

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

What to expect, from measurements on a busy 8 GB laptop (a 16 GB VM should not be slower): the offline
suite takes well under half a minute; the first Structr boot about a minute; the rebuild of all 48 scripts 4-8 minutes.

## Day to day

- **Each new session starts with no running stack and no data.** For offline work (tests, the planner,
  documents) that does not matter. For anything against Structr, ask for `bash cloud/bootstrap.sh`
  and then `bash tools/rebuild.sh`. A session that sits idle is reclaimed, and a rebuild running in
  the background at that moment is lost; start it again.
- **Results arrive as a branch.** Cloud sessions push a branch and can open a pull request from
  claude.ai/code; you review and merge. The house rule still holds: nothing is committed or pushed
  without you saying yes. To continue a cloud session on your laptop:
  `claude --teleport` from a checkout of the repository (it asks you to stash uncommitted changes first).
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
- The stack's ports stay inside the VM. Do not paste a real credential into a cloud session: its
  transcript is stored on claude.ai, and a shared session shows what it contains.
- Keep sessions Private unless you mean to share one.

## Limits

- Cloud sessions share your account's rate limits; several in parallel use them up faster.
- The VM's ceilings are approximate (4 vCPUs, 16 GB, 30 GB); the images and a built instance are a
  few GB, so there is room.
- The setup script's result is cached only if it finishes in about five minutes, and the cache is
  rebuilt when the script or the network settings change and after roughly a week.
- A command Claude runs waits two minutes by default (up to ten if asked) before moving to the background.

## First-run checklist: not verified from here

I could test the scripts against a fake Structr and against your real one, but not inside a cloud VM.
The smoke test above settles each of these; anything that fails is a fix to a script, not to the plan:

1. The Docker daemon is running (or `service docker start` starts it) and `docker compose up -d` works.
2. `cloud/setup.sh` finishes within five minutes, exits 0, and the two images are on disk afterwards.
3. `python3 -m pip install --break-system-packages requests` and the venv creation work in the VM; the
   solver venv ends up at `/opt/solver-venv` and passes the 9 solver tests.
4. Structr boots in the VM's memory and answers within the wait (`WAIT_S`, default 300 seconds).
5. `tools/rebuild.sh` prints `SNAPSHOT IDENTICAL`.
6. Whether the session can push a branch, and whether it can push to `main` directly (this file
   assumes a branch).
7. The environment variables are visible to Claude's commands (`bootstrap.sh` reads them).

## If cloud sessions do not suit

The reason to leave them would be needing the database to persist between sessions. The alternative
is a small server: Hetzner's CX33 (4 vCPUs, 8 GB) was 8.49 euros a month plus VAT in June 2026. The
same `cloud/bootstrap.sh` and `tools/rebuild.sh` work on it unchanged, with Claude Code installed on
the server and used over SSH. Keep Structr's port off the public internet (SSH tunnel or a VPN).
