# Review guide

A solo, AI-assisted build of a BFO-grounded meal-planning data model on Structr 6.x/Neo4j. This is the second external code review. The first reviewed the repository as it stood at commit `0cc20f1`; this guide says what became of each of its findings, what a pre-review self-audit found on top, and what is still open.

Nothing here asks you to trust a claim. Every "fixed" below names a commit and a script you can run, and every "open" says why it is open. Where a claim was found smaller or wrong, that is stated too.

## What is being reviewed

- **Correctness of the computations** (`mealplanner/`): inventory and expiry, unit conversion, reservation and the shopping list, nutrition scoping, stock-policy resolution, exclusions.
- **The Structr client and schema helpers** (`structr_client/`), including how they behave against a schema that has drifted.
- **The model itself** (`docs/data-model.md`), especially Rev 4.3 (§17) and Rev 4.4 (§18), which record resolutions chosen under implementation pressure.
- **Whether the repo is honest about itself:** does a fresh build reproduce what it claims, do the tests test what they say, does the invariant tracker match reality.

Start with `docs/CLAUDE.md` for the document-authority table and the hard rules, then this file. The two `docs/design-review-document*.md` files are historical and describe the model *before* their own fixes; do not review the current model against them.

## Deliberately out of scope

`docs/CLAUDE.md` lists things considered and declined (single-user by design, no per-serving customization, no freeze/thaw state transitions, no non-linear scaling, free-text shelf location, no OWL reasoning). Flagging their absence is not useful. **There is also no optimizer:** selection is a filter plus a weighted scorer, built as a first step, and no numeric definition of a good week exists.

## Running it

```bash
cp .env.example .env && docker compose up -d
set -a && source .env && set +a
python3 scripts/23a_schema_drift_test.py                    # offline, no Structr needed
for f in $(ls scripts/*.py | sort -V); do python3 "$f" || break; done   # full build
python3 tools/snapshot_state.py | diff - tools/expected_state.json && echo identical
```

**Verified from scratch.** On an empty instance (fresh containers and volumes), the loop above ran all 44 scripts to completion in about six minutes on a warm machine; it stops at the first failure, so none failed. The snapshot check then reports no difference, and a snapshot of the maintainer's working instance is byte-identical to it: 214 named entities on each side. Only the maintainer's environment has been tested (Linux, Docker, Structr 6.0.0, Neo4j 2025.12.1); a first boot on a cold machine takes several times longer.

This was not always true, and the check is why it is now. Before this pass the same rebuild failed two scripts and left about 40 entities and 40 property values unreproduced (item 1 of the self-audit below). `tools/expected_state.json` is a golden file: if you change what a script creates, regenerate it and read the diff.

## Round 1: what became of each finding

The first review made 25 numbered points. Each was checked against the code and the live instance before anything was changed.

| # | Finding | Status |
|---|---|---|
| 1 | `ensure_type` violated the project's own "never change a populated type's traits" rule | **Fixed** (`e767abd`, `cc92fb0`). Drift now raises `SchemaDriftError`; `isAbstract` is compared too |
| 2 | `ensure_property` / `ensure_relationship` accepted a live schema that differed from the code | **Fixed** (`cc92fb0`), and the strict helpers immediately found a real drift (below). Tested offline by `23a`, and against every schema script on a live schema |
| 3 | `expected_combination_output` returned after the first Step | **Fixed** (`e767abd`). It was uncalled dead code, so nothing was corrupted; it is now used to compute the combination recipes' outputs. The chained-Step double-count is an open modeling question |
| 4 | Stock scoring ignored units | **Fixed** (`e767abd`, `unit_conversion.py`, invariant 13). Limits: only density and mass-per-unit conversions, only two placeholder defaults exist, and the unit table is hard-coded rather than the SKOS scheme the model describes |
| 5 | Daily/weekly nutrition targets judged per meal | **Fixed** (`54b5538`, `nutrition_scope.py`; model §18 J3/J4) |
| 6 | The selector isn't plan-level | **By design, unchanged.** Still greedy per slot; stock and nutrition now see already-planned entries, but nothing optimizes jointly |
| 7 | No reservation layer | **Partly fixed** (`e767abd`). Raw-ingredient reservation for fresh-cook entries and `net_requirements()` exist. Leftover surplus (invariants 23/24) is not built |
| 8 | Expiry anchored to the latest mass measurement | **Open.** Known and documented in `inventory.py`; needs a shelf-life start timestamp or a Purchase Process |
| 9 | "No container" means two different things | **Open, needs a decision.** Expiry assumes Sealed and Fridge; eligibility filters treat it as "filter doesn't apply". Both documented |
| 10 | First applicable StockPolicy wins | **Fixed** (`e47bc30`, `resolve_stock_policy`; model §18 J2) |
| 11 | Exclusions one hop deep | **Fixed** (`e47bc30`; §18 J6). A type *above* an excluded one is not banned, which for allergies is a choice worth challenging |
| 12 | Required-type set loses multiplicity | **No change.** It feeds only the set-membership exclusion check, where multiplicity is irrelevant; quantities have their own function |
| 13 | Only the first output considered | **Fixed** (`e47bc30`, `candidate_outputs`; §18 J5) |
| 14 | Missing yield defaults to 1 serving | **Partly fixed.** Nutrition is strict (`54b5538`). **Reservation still uses the lenient `recipe_servings` and defaults to 1.** Open |
| 15 | Difficulty authored or derived? | **Open.** It is an authored enum today; the model leans toward derived |
| 16 | `Function` is unused | **Open** |
| 17 | Numeric truthiness (`or 1.0`) | **Checked, mostly not live.** Invariant 14 already rejects a zero yield, and the other sites treat 0 and None identically. Unchanged; the pattern remains fragile |
| 18 | Tied timestamps can't be ordered | **Open.** `current_magnitude` treats a Process at the same instant as a measurement as after it; documented |
| 19, 20 | REST N+1 traversal | **Open, now measured:** one selector run over 4 recipes and 17 stock portions makes 256 HTTP requests and takes about 18 s. It scales with recipes x ingredients x portions and is not usable beyond toy size |
| 21 | Docs and code can drift | **Partly fixed.** `docs/` verified identical to the working copies; §18 records the semantics that had lived only in code comments. No machine-checkable schema manifest exists, and `docs/CLAUDE.md`'s status table still says Rev 4.2 |
| 22 | Invariant tracker needs three states | **Partly.** The tracker now separates structural / write-time / computation / partial / deferred, and covers all 30 (below). It does not use the reviewer's exact vocabulary |
| 23 | Test scripts leave state behind | **Partly fixed.** `16b`, `20a`, `21a`, `22a` remove what they create. `15e` removes its probe allocation but leaves its "Leftover test week" plan and entries in place on purpose, because `16b` builds on them; the older breadth scripts (`08`, `09`) leave everything until `15a` wipes it |
| 24 | Placeholder nutrient data can satisfy hard constraints | **Open.** Profiles are labelled PLACEHOLDER by name, but nothing stops them deciding a hard constraint |
| 25 | Several meanings of "is a kind of X" | **Partly.** `subtypes_of` is shared by exclusions, stock and policy resolution; `resolveDefault` (StructrScript) remains a separate traversal |

Findings that turned out smaller than reported: #3 (dead code), #8 (already self-documented), #17 (guarded by an invariant). They were still worth reading, and #8 in particular is independently confirmed.

## Found by the pre-review self-audit

These were not in the first review.

1. **The live instance disagreed with the committed scripts.** Rebuilding from scratch and diffing against the working instance showed about 40 entities and 40 property values that no script produced: three yield defaults, four compound shelf-life defaults, servings-denominated yields, computed recipe outputs, and the opened-status, storage-condition and leftover-reservation fixtures. They came from ad-hoc verification code in earlier sessions, so this file's earlier claim that "the scripts are the reproducible source of truth" was false. All of it is now captured in scripts (`15b`, `15c`, `15d`, `16b`, `17b`, `17c`, `17d`, `18b`; commit `1675630`), and a from-scratch build is compared with the working instance (see the reproduction result above).
2. **Script order was not dependency order.** `15f` needs the `Sealed` type and compound shelf-life defaults that `17a`/`17b` create, so on a fresh build it crashed. It is now `17c`.
3. **Invariant 27a had no committed test.** A commit claimed it was "verified against a correct case and a deliberately wrong one" by ad-hoc code. `16b` is that check: one accepted case and two rejected, each with the right error token.
4. **The invariant tracker omitted four of the thirty** (2, 10, 25, 27). Invariant 2's `hasTime` is an optional Date, so a Measurement without a time is accepted and `inventory.py` then silently ignores it.
5. **`net_requirements()` ignored a StockPolicy's eligibility filters** while the selector applied them, so the shopping list disagreed with the selector about the same stock. Found by re-running a demo weeks later, after test inventory had aged out. Fixed in `54b5538`.
6. **Guards could be bypassed.** The comma-in-name guard covered `upsert()` only; a Role and three Measurements were created with commas through direct `POST`s. The guard now lives in `post()` (`1675630`).
7. **A schema drift the old helpers hid:** `06a` declared `hasParticipationRole` as nullable while `07_domain_invariants.py` later patched it to `notNull` directly. Fixed in `cc92fb0`.
8. **README bug:** it told readers to copy `.env.example` but never to load it into the shell, so every script raised `KeyError`.
9. **Reproducibility hygiene:** Neo4j was `latest` (now pinned to the running version), the compose port was fixed (now `STRUCTR_PORT`), and `structr/license.key` is an intentionally empty placeholder for a bind mount, now commented as such.

## Open items

Beyond the open rows above:

- **Variety scoring** treats an entry planned for the future as "just used" (days-ago goes negative, clamped to zero), so already-planned recipes are penalized. It is also global across MealPlans. Neither was examined.
- **Reservation scaling** defaults an unset recipe yield to 1 (see #14).
- **Invariants:** 12 deferred (9, 11, 15-24) plus 2b and 9a. Invariant 15 has **no enforcement at all**: an allocation of 500 g against 200 g on hand is accepted. `scripts/15e` demonstrates it.
- **Duplication:** 14 scripts define their own `dt()`, and 39 define the same URL/user/password constants. A `StructrClient.from_env()` and a shared lookup helper would remove most of it.
- **No automated suite** beyond `23a` and the demo scripts. The 30 invariants were meant to be the test suite; about a third have a check.
- `docs/CLAUDE.md`'s document-status table names Rev 4.2; the model is at 4.4.

## Where a review would help most

1. **The model, §17 and §18.** These are judgment calls made while implementing, not derivations. The ones most worth an ontologist's challenge: J1 (reading `AcquisitionList` as one shared pool), J2 (nearest-policy-wins and restrictive ties), J5 (deriving "final output" from Plan structure), J6 (exclusion not extending upward).
2. **Try to break the computations** with data the fixtures don't contain: a recipe whose output is also an input, two policies at different depths, a stock portion with a measurement but no time, a container with no state, a target in an odd unit. Several scripts show how to build isolated throwaway fixtures (`22a` builds and removes its own).
3. **The schema helpers.** `SchemaDriftError` refuses to reconcile; is there a legitimate migration path it makes too hard, and is every attribute that matters compared?
4. **Test quality.** Which scripts assert against the engine's own output rather than independently worked-out values? `22a`, `21a`, `17d`, `18b` were written to avoid that; the older ones (`08`, `09`, `15e`) may not.
5. **General code quality:** the duplication above, the script/module boundary (`11c` is both a library and a demo), and error handling.

## Test-data convention

Illustrative and test instance data is name-prefixed `TEST -- `; curated vocabulary is not, and placeholder vocabulary values carry `[PLACEHOLDER -- not sourced from USDA/FDC yet]` in their names.

**Audited at the end of a from-scratch build:** 214 named entities, 128 `TEST`-marked and 86 unmarked. All 86 are vocabulary: `DomainType` (45), `TypeHierarchy` (13), `DefaultSpecification` (10) with the `QuantitySpecification` values they point at (10), `NutrientProfile` (3), and the meal-type `Concept`s and scheme (5). No instance data (recipes, portions, processes, measurements, meal plans) is unmarked, and every default value and profile carries the placeholder marker in its name. The step-6 worked example (`06b`-`06d`) does create unmarked instance data, but `15a` deletes it and `15c` rebuilds it as `TEST` data, so it exists unmarked only between those scripts.
