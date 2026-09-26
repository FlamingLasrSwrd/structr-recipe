# structr-recipe

A BFO-grounded data model for a single-user meal-planning tool, built on Structr 6.x (a graph-database-backed low-code platform, running on Neo4j). The model is implementation-agnostic and covers recipes, inventory, cooking, meal planning, and nutrition; this repo is the Structr build of it, done incrementally with an AI assistant across several sessions, each step verified against a live instance rather than assumed correct.

The design work (BFO/IAO/RO/PROV-O grounding, four major model revisions, two adversarial design reviews) came first and is documented under `docs/`. This repo is where that model got built and tested.

## Status

A working spike, not a finished product, and not yet an optimizer: meal selection is a hard-constraint filter plus a weighted scorer, with a real optimizer design left for later. It has been through one external code review, whose findings were checked against the code and mostly fixed; `REVIEW.md` says what was fixed, what was found smaller than reported, and what is still open, and it is the place to start if you are reviewing.

Of the model's 30 domain invariants (tracked in `mealplanner/domain_invariants.py`): 9 are enforced as write-time checks, 2 hold structurally, 2 are computations rather than validators, 1 is partial, 12 are deferred with reasons, and 4 were missing from the tracker until a self-audit before the second review.

## Layout

- `docs/` — the design documents. `data-model.md` and `structr-build-sketch.md` are authoritative; `structr-cheatsheet.md` is empirically verified Structr mechanics; `CLAUDE.md` holds the hard rules this build followed and a document-authority table. Read `CLAUDE.md` first. The two `design-review-document*.md` files are historical: they describe the model *before* their own fixes and should not be followed.
- `mealplanner/` — the project's Python: schema declarations (`*_schema.py`), domain-invariant validators, the compute-don't-store engines (`inventory.py`, `material_accounting.py`, `unit_conversion.py`, `reservation.py`, `nutrition_scope.py`), and vocabulary seeds.
- `structr_client/` — a small generic Structr REST client with no project knowledge, kept separate on purpose. Its schema helpers refuse to reconcile drift (`SchemaDriftError`).
- `tools/` — `snapshot_state.py` dumps the graph as normalized JSON; `expected_state.json` is the known-good result of a full build.
- `scripts/` — numbered in build order. Most build schema or seed data and verify themselves; `11c` is the selector; `20a`–`22a` are self-cleaning demonstrations of specific fixes; `23a` is an offline test.
- `REVIEW.md` — guide for reviewing this repo.

## Running it

Requires Docker and Python 3 with `requests`.

```bash
cp .env.example .env            # then edit the two passwords
docker compose up -d            # first boot takes a minute or two
set -a && source .env && set +a # the scripts read the password from the environment
```

Wait until `http://localhost:8083/structr/rest/SchemaNode` answers, then run the scripts in numeric order:

```bash
for f in $(ls scripts/*.py | sort -V); do echo "== $f"; python3 "$f" || break; done
```

Each script prints its own verification. Most are safe to re-run. To check that your instance now holds exactly what the maintainer's does:

```bash
python3 tools/snapshot_state.py | diff - tools/expected_state.json && echo identical
```

To use a different port, or a second instance alongside an existing one:

```bash
STRUCTR_PORT=8084 docker compose -p structr-second up -d
export STRUCTR_URL=http://localhost:8084
```

`scripts/23a_schema_drift_test.py` needs no Structr at all:

```bash
python3 scripts/23a_schema_drift_test.py
```

The default superuser is `superadmin` (not `admin`), authenticated with `X-User`/`X-Password` headers; see `docs/structr-cheatsheet.md` for Structr REST details. `structr/license.key` is an intentionally empty placeholder so the compose bind mount has a file to attach to.

## License

MIT — see `LICENSE`.
