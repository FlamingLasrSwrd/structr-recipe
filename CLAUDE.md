# CLAUDE.md (repository root)

Operating instructions for any Claude Code session in this repository: a local one, or one
in the cloud (see CLOUD.md). Read `docs/CLAUDE.md` first. It holds the hard rules that protect
the data and the document-authority table, and this file does not repeat them.

## The design documents live only in `docs/`

Decided by the owner on 2026-09-26: `docs/` is the ONLY copy of the design documents, in a laptop
session and a cloud session alike. An older Obsidian vault copy exists on the owner's laptop and is
frozen. Never edit it, never copy to it, and if you find yourself in a directory that holds an older
`CLAUDE.md` or `data-model.md`, stop: the current ones are in this repository's `docs/`. Edit
documents directly in `docs/`, in the same commit as the code they describe.

## What this is

A BFO-grounded data model for a single-user meal planner, built on Structr 6 and Neo4j, plus the
Python that computes over it: inventory, reservation, nutrition, a per-slot selector, and a
plan-level planner (`mealplanner/planning/`). The public repository is used for external code
review, so what the README and REVIEW.md claim has to be true.

## Working agreements (the owner's, learned the hard way)

- **Commit and push each verified batch without waiting for a yes** (the owner's deliberate
  choice, 2026-09-26; it used to be ask-first). Finish and verify a batch before committing it,
  and say what you did and why in your report. Stage explicit file names, never `git add -A`.
  Write a message that says why. End it with the Co-Authored-By trailer. Plain fast-forward
  push; never force. Never rewrite published history. In a cloud session, push to the session's
  branch, not `main` (see below).
- **Look at `git status` and `git diff` before committing and read every hunk you did not
  write.** Another Claude session may have edited the same tree. Flag foreign changes; do not
  revert them.
- **Every change to a live instance's data goes through a committed, idempotent, numbered
  script**, never inline Python or a one-off PATCH. An instance must always be reproducible
  from `scripts/`; a rebuild once found about 40 entities no script produced.
- **The owner's own data is the one exception, and it lives only in the owner's instance**
  (decided by the owner 2026-09-26: "my data would live in the structr instance"). That
  instance is its own compose project on port 8085 (`tools/owner_stack.sh`), built once and
  never rebuilt; the development stack (8083) and throwaway stacks hold only reproducible data.
  Owner data goes in through committed, idempotent tools (`tools/import_recipe.py`) whose input
  files live in `private/`, which git ignores: the repository is public, the owner's data is
  not. Never run a demo from `scripts/` against it (`connect()` refuses a marked instance), and
  never `down -v` it: nothing can rebuild it. The exception is a schema-only migration (such as
  `30a`, `31a`, `32a`, `33a`), which declares `owner_data_ok=True` and must be run on the owner's instance as well,
  then Structr restarted (hard rule 8).
- **The development laptop has 8 GB and has frozen three times.** Run one stack at a time (stop
  one before starting another), stop a stack once its work is done, and check `free -m` before
  starting one or a heavy step. `docker-compose.yml` caps each stack (Neo4j 1 GB, Structr 1.5 GB);
  do not raise the caps without measuring. Avoid loading large files repeatedly (the FNDDS JSON is
  about 450 MB in Python; `data/fdc/` already pins what is needed), and close built-in browser
  tabs as soon as they have been read.
- **Test data is named `TEST -- `.** Demos and checks delete what they create, and sweep what an
  interrupted earlier run left.
- **Expected values in a test are worked out independently of the code under test**, by hand or
  by a separate enumeration, and must not depend on there being no other data on the instance.
- **A test that has never failed proves little.** Break the code on purpose and confirm the
  test notices (this has found real gaps). Report failures with their output; say what you did
  not verify.
- No emojis in README.md or LICENSE. Never print, log or commit `.env` or a password.
- An optimizer objective, weights or search are proposals for the owner to retune
  (`docs/optimizer-design.md`): do not change them silently.

## Commands

```bash
python3 -m unittest discover -s tests -t .        # offline; no Structr needed (9 solver tests skip without OR-tools)
.venv/bin/python -m unittest discover -s tests -t .   # the same with OR-tools (locally: .venv; cloud: /opt/solver-venv/bin/python)
python3 tools/check_names.py                       # undefined names and unused imports (no pyflakes here)
python3 scripts/23a_schema_drift_test.py           # offline schema-helper test

bash cloud/bootstrap.sh            # stack up: makes .env if missing, docker compose up, waits for Structr
bash tools/rebuild.sh              # every script in build order, then the snapshot check (SNAPSHOT IDENTICAL)
set -a && source .env && set +a    # before running any single script by hand
python3 tools/snapshot_state.py | diff - tools/expected_state.json   # instance vs golden

bash tools/owner_stack.sh up       # the owner's instance (8085); stop the development stack first
STRUCTR_URL=http://localhost:8085 python3 tools/import_vocabulary.py   # data/vocabulary.toml; --check validates only
STRUCTR_URL=http://localhost:8085 python3 tools/import_recipe.py private/recipes/*.toml
STRUCTR_URL=http://localhost:8085 python3 tools/import_profiles.py     # data/profiles/*.toml; --check validates only
STRUCTR_URL=http://localhost:8085 python3 tools/instantiate_profile.py kitchen --list   # or pantry --list; then nutrition|kitchen|pantry private/<file>.toml (docs/profiles.md)
STRUCTR_URL=http://localhost:8085 python3 tools/import_recipe.py private/baseline.toml    # the daily baseline (supplements)
STRUCTR_URL=http://localhost:8085 python3 tools/plan_week.py private/week.toml            # propose a week and report nutrients; --commit writes it
python3 tools/fdc_extract.py        # after adding a food: re-pins data/fdc/ from the datasets in .cache/fdc/ (loads the FNDDS JSON, ~450 MB)
```

Both interpreters must pass the whole suite. `tools/expected_state.json` is a golden file: if a
script's output changes on purpose, regenerate it and read the diff.

## Where things are

`docs/` design documents (authoritative order is in `docs/CLAUDE.md`) - `mealplanner/` the Python
(`planning/` is the planner) - `structr_client/` a generic REST client, no project knowledge -
`scripts/` numbered build and demo scripts - `tools/` snapshot, rebuild, checks - `tests/` offline
tests over an in-memory graph - `REVIEW.md` what became of every review finding.

## In a cloud session

`CLAUDE_CODE_REMOTE=true` there. What differs from a laptop:

- **The database does not persist.** A new session has images on disk but no running stack and no
  data. Run `bash cloud/bootstrap.sh`, then `bash tools/rebuild.sh` (several minutes: run it in the
  background and read its log, since a command that runs long is moved to the background anyway).
  You only need a live instance for the scripts, not for the offline tests.
- **Passwords are throwaway** and come from the environment's variables (or are generated). The
  instance is disposable: never treat it as the owner's data, and never put a real secret in it.
- **Memory does not carry over**; this file and `docs/CLAUDE.md` are what you have.
- You work on a branch that gets pushed; the owner merges. Do not assume you can push to `main`.
