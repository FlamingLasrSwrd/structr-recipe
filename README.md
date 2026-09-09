# structr-recipe

A BFO-grounded data model for a single-user meal-planning tool, built on Structr 6.x (a graph-database-backed low-code platform, running on Neo4j). The model is implementation-agnostic and covers recipes, inventory, cooking, meal planning, and nutrition; this repo is the Structr build of it, done incrementally with an AI assistant across several sessions, each verified against a live instance rather than assumed correct.

The design work (BFO/IAO/RO/PROV-O grounding, four major model revisions, two adversarial reviews) came first and is documented in full under `docs/`. This repo is where that model actually got built and tested.

## Status

This is a working spike, not a finished product. Roughly a third of the model's 30 domain invariants are enforced; the rest are either genuinely blocked on unbuilt structural pieces or deliberately deferred, all tracked in `mealplanner/domain_invariants.py`. There is no optimizer — the meal-selection logic is a simple, explicitly-weighted scorer, built as a first step with a real optimizer design left for later. See `REVIEW.md` for a fuller list of open questions and self-reported findings.

## Layout

- `docs/` — the design documents: `data-model.md` and `structr-build-sketch.md` are authoritative; `structr-cheatsheet.md` is empirically-verified Structr mechanics; `CLAUDE.md` has the hard rules this build followed and a document-authority table. Read `CLAUDE.md` first.
- `mealplanner/` — the project's own Python: schema definitions, domain-invariant validators, the inventory and material-accounting engines, vocabulary seeds.
- `structr_client/` — a small, generic Structr REST client with no project-specific knowledge, kept separate on purpose.
- `scripts/` — numbered in build order, each independently re-runnable and self-verifying. See `REVIEW.md` for what each range of numbers covers.
- `REVIEW.md` — a guide for reviewing this repo, including a checklist of self-reported findings worth independent confirmation.

## Running it

Requires Docker.

```bash
cp .env.example .env   # then edit the two passwords
docker compose up -d
```

Wait for `http://localhost:8083/structr/rest/SchemaNode` to return 200 (first boot takes a while), then run the scripts under `scripts/` in numeric order. Each one prints its own verification as it goes; most are safe to re-run.

The default superuser account is `superadmin` (not `admin`), authenticated via `X-User`/`X-Password` headers — see `docs/structr-cheatsheet.md` if you're working with the Structr REST API directly.

## License

MIT — see `LICENSE`.
