# Review guide

A solo, AI-assisted build of a BFO-grounded meal-planning data model on Structr 6.x/Neo4j. This is the third external code review. The first reviewed the repository at commit `0cc20f1`; the second reviewed `e8d1cbf`. This guide says what became of every finding from both, what our own audits found on top, and what is still open.

Nothing here asks you to trust a claim. Every "fixed" names the code and a test you can run, and every "open" says why it is open. Where a review was found to be wrong or overstated, that is stated too, with the evidence.

## What is being reviewed

- **Correctness of the computations** (`mealplanner/`): inventory and expiry, unit conversion, default resolution, reservation and the shopping list, nutrition scoping, stock-policy resolution, exclusions.
- **The Structr client and schema helpers** (`structr_client/`).
- **The model** (`docs/data-model.md`), especially §17 (Rev 4.3) and §18 (Rev 4.4), which record resolutions chosen under implementation pressure rather than derived.
- **Whether the repo is honest about itself:** does a fresh build reproduce what it claims, do the tests test what they say, do the documents agree with the code.

Start with `docs/CLAUDE.md` (document authority and hard rules), then this file. The two `docs/design-review-document*.md` files are historical and describe the model *before* their own fixes.

## Deliberately out of scope

`docs/CLAUDE.md` lists things considered and declined (single-user, no per-serving customization, no freeze/thaw state, no non-linear scaling, free-text shelf location, no OWL reasoning). **There is also no optimizer:** selection is a filter plus a weighted scorer, and no numeric definition of a good week exists.

## Running it

```bash
python3 -m unittest discover -s tests -t .        # offline unit tests: no Structr needed
python3 scripts/23a_schema_drift_test.py           # offline: the schema helpers vs a drifted schema

cp .env.example .env && docker compose up -d
set -a && source .env && set +a
for f in $(ls scripts/*.py | sort -V); do python3 "$f" || break; done     # full build, stops at the first failure
python3 tools/snapshot_state.py | diff - tools/expected_state.json && echo identical
```

The offline tests also run on every push (`.github/workflows/tests.yml`).

**Verified from scratch.** On an empty instance (fresh containers and volumes) the loop above ran all 45 scripts to completion in about ten (six when the containers were already warm) minutes on a warm machine; it stops at the first failure, so none failed. The snapshot check then reports no difference, and a snapshot of the maintainer's working instance is byte-identical to it: 214 named entities plus 169 schema entries (every type, property, relationship, and the full source of every validator) on each side. The schema is in the snapshot because a validator is a method and can be silently replaced, which is what script `04` once did to script `07`'s. Only the maintainer's environment has been tested (Linux, Docker, Structr 6.0.0, Neo4j 2025.12.1); a first boot on a cold machine takes several times longer. This was not always true (self-audit item 1). `tools/expected_state.json` is a golden file: if a script's output changes, regenerate it and read the diff.

## Round 2: the review of `e8d1cbf`

24 numbered points. Each was checked against the code and the live data first. The fixes are in commit `29b41cc`.

| # | Finding | Status |
|---|---|---|
| 1 | `current_magnitude` used measurements and processes from the future | **Fixed.** Bounded by `now` for the baseline and for consumption; `instance_expiration` too. `tests/test_inventory.py`. The old code reproduces all three symptoms (420 g instead of 500, a not-yet-happened process already consuming) |
| 2 | Allocation quantities subtracted without unit conversion | **Fixed.** Everything is converted to grams first; an unusable quantity raises `QuantityError` instead of counting as zero. The old code said a 0.5 kg baseline minus 100 g left **-99.5 g**. Measurements now need a unit at write time. `expected_combination_output` had the same flaw and is fixed too |
| 3 | Reservation keyed to the candidate type, not the stock pool | **Fixed, with a correction.** The review's concrete example does not occur (the selector computes eligibility at the ingredient's own type, so a turkey recipe never sees chicken's stock). The underlying scope mismatch was real in both directions, though: a generic "Poultry" demand ignored a chicken reservation, and vice versa. Availability is now computed along the type tree (model §18 J7). Unit tests plus a live check in `22a` |
| 4 | `StockPolicy` target/threshold compared without units | **Fixed.** Write-time rule: same unit. `24a` |
| 5 | `resolveDefault` ignores `keyedBy` | **Fixed.** Resolved in Python by (kind, keys) with defined precedence (`mealplanner/defaults.py`, §18 J9), used for yields, shelf lives, densities and mass-per-unit. The StructrScript method remains, kind-only, and nothing in `mealplanner/` calls it |
| 6 | `expected_combination_output` is dead code and can't handle chained recipes | **Half wrong.** "Dead code" was my own stale docstring; `15c` has used it to compute recipe outputs for a while, and the docstring is corrected. The chained-recipe point is **right and still open**: it needs a material-flow model over the Steps, not a Plan-wide sum |
| 7 | Exclusions inspect instruments, outputs and optional inputs as ingredients | **Fixed** (§18 J10): non-optional inputs and outputs count; instruments never; an optional excluded input is reported so it can be left out. Unit tests, and a live check in `22a` |
| 8 | `Measurement.hasTime` required but not enforced | **Fixed.** `notNull`, migrated on the live instance by `07` (the drift-detecting helper refused the new declaration until it ran, which is what it is for) |
| 9 | Range quantities bypass the negative check | **Fixed, and it was wider than reported:** a `QuantitySpecification`'s scalar value had no negative check either. `24a` |
| 10 | Zero treated as missing (`or` defaults) | **Fixed** in the selector (a zero weight became 0.5, a zero time budget became 60 and would have divided by zero), and in the yield and servings readers. A related sort bug (`score or -1` ranked a 0 below a negative) is fixed. `tests/test_selector.py` |
| 11 | `upsert()` patches the first of several matches | **Fixed.** `DuplicateMatchError`; writes nothing |
| 12 | Unsafe-character guard incomplete | **Fixed.** One `validate_exact_match_value` for comma and semicolon, applied to POST, PATCH and upsert. The semicolon behaviour comes from Structr's documentation; I did not reproduce it |
| 13 | `wait_until_ready` hides authentication errors | **Fixed.** Retries connection errors, timeouts and 5xx; any other HTTP error fails immediately. A real cold boot passes |
| 14 | No request timeout | **Fixed.** Default (5 s connect, 120 s read), configurable |
| 15 | N+1 REST traversal | **Open, and slightly worse.** One selector run over 4 recipes and 17 stock portions makes **303 HTTP requests (19 s)**, up from 256 (18 s) before this pass: the stricter engine reads each portion's food type for unit conversion and the default resolver walks the type tree. The new availability logic only scans an ancestor's stock when something outside the type's own subtree has claimed it, so it adds nothing in the common case. Still not usable beyond toy size |
| 16 | Same-instant events are undecidable (`>=`) | **Open.** A test now pins the current convention so a change is deliberate |
| 17 | Expiry anchored to the latest weighing, not a Purchase Process | **Open.** It is bounded by `now` (a future weighing can no longer push expiry out) but still anchored to the weighing |
| 18 | "No container" means two different things | **Open, needs a decision** |
| 19 | Nested StockPolicies double-count stock | **Fixed:** the nearest policy owns the physical stock (§18 J2). Unit test plus a live check |
| 20 | Soft `ExclusionConstraint`s do nothing | **Fixed:** a soft exclusion costs the candidate its weight (§18 J10) |
| 21 | Greedy selection can't enforce hard minimums | **Open, by design.** This is the optimizer's job; §18 J4 records the boundary |
| 22 | Documents drift from each other and the code | **Partly fixed.** `CLAUDE.md` said Rev 4.2 while the model was 4.3. Now `tests/test_docs.py` fails if the revision, the structural-type count, or the invariant tracker's coverage disagree with the code. There is still no machine-readable manifest |
| 23 | "~35" vs 50 structural types | **Fixed, and the fix was itself wrong first.** I copied "50" from a comment in `structural_types.py`; the new test showed the real count is **51** (`ExclusionConstraint` was added after that comment was written). All three places corrected |
| 24 | Not enough automated tests | **Fixed in part:** an offline suite over the pure logic (`tests/`, no Structr), run by CI. It covers the review's own list: future events, mixed units, zero values, optional ingredients, subtype/supertype collisions, overlapping policies, multiple defaults, multiple outputs. Still missing: most invariants have no test beyond the demo scripts |

**The review's suggested architecture**, one shared "which stock pool does this belong to" layer, is partly done: `typetree.py`, `defaults.py` and `reservation.Reserved` now own the hierarchy walks, default resolution and pool accounting that used to be reimplemented per module. Pool resolution for eligibility, policy and waste scoring is still spread across `reservation.py` and the selector.

**Where the review was wrong or overstated:** #3's example, #6's "dead code", #12's semicolon (unreproduced). It was right about everything else I checked, including several things worse than stated (#2, #9).

## Round 1: the review of `0cc20f1`

| # | Finding | Status |
|---|---|---|
| 1 | `ensure_type` violated "never change a populated type's traits" | **Fixed.** `SchemaDriftError`; `isAbstract` compared too |
| 2 | `ensure_property` / `ensure_relationship` accepted schema drift | **Fixed**, and the strict helpers immediately found a real drift (`06a` declared a property nullable that `07` had made `notNull`). Tested offline by `23a` and against every schema script |
| 3 | `expected_combination_output` returned after the first Step | **Fixed** (see round 2 #6) |
| 4 | Stock scoring ignored units | **Fixed** (`unit_conversion.py`, invariant 13) |
| 5 | Daily/weekly nutrition judged per meal | **Fixed** (`nutrition_scope.py`; §18 J3/J4) |
| 6 | The selector isn't plan-level | **By design, unchanged.** Greedy per slot |
| 7 | No reservation layer | **Partly fixed.** Raw-ingredient reservation and `net_requirements()` exist; leftover surplus (invariants 23/24) is not built |
| 8 | Expiry anchored to the latest measurement | **Open** (round 2 #17) |
| 9 | "No container" means two things | **Open** (round 2 #18) |
| 10 | First applicable StockPolicy wins | **Fixed** (§18 J2) |
| 11 | Exclusions one hop deep | **Fixed** (§18 J6). A type *above* an excluded one is not banned, which for allergies is a choice worth challenging |
| 12 | Required-type set loses multiplicity | **No change.** It feeds a set-membership check where multiplicity is irrelevant |
| 13 | Only the first output considered | **Fixed** (§18 J5) |
| 14 | Missing yield defaults to 1 serving | **Partly fixed.** Nutrition is strict. **Reservation still uses the lenient `recipe_servings` and defaults to 1.** Open |
| 15 | Difficulty authored or derived? | **Open** |
| 16 | `Function` is unused | **Open** |
| 17 | Numeric truthiness (`or 1.0`) | **Underrated at the time.** I judged the sites I looked at harmless because invariant 14 forbids a zero yield; round 2 #10 then showed the selector's `or` defaults were real bugs. All are now explicit `is None` checks |
| 18 | Same-instant events | **Open** (round 2 #16) |
| 19, 20 | REST N+1 | **Open** (round 2 #15) |
| 21 | Docs and code drift | **Partly fixed** (round 2 #22) |
| 22 | Invariant tracker needs states | **Partly.** It separates structural / write-time / computation / partial / deferred and covers all 30; `tests/test_docs.py` enforces the coverage |
| 23 | Test scripts leave state behind | **Partly fixed.** `16b`, `20a`, `21a`, `22a`, `24a` remove what they create. `15e` leaves its "Leftover test week" on purpose (`16b` builds on it); `08` and `09` leave everything until `15a` wipes it |
| 24 | Placeholder nutrient data can satisfy hard constraints | **Open** |
| 25 | Several meanings of "is a kind of X" | **Partly.** `typetree.subtypes_of` and `ancestors_or_self` are shared; `resolveDefault` (StructrScript) is a separate traversal that no longer matters to `mealplanner/` |

## Found by our own audits

Between and before the reviews.

1. **The working instance disagreed with the committed scripts.** A from-scratch rebuild diffed against it showed about 40 entities and 40 property values no script produced, from ad-hoc verification code in earlier sessions. Captured in `15b`, `15c`, `15d`, `16b`, `17b`, `17c`, `17d`, `18b` (commit `1675630`).
2. **Script order was not dependency order:** `15f` needed what `17a`/`17b` create; it is now `17c`.
3. **Invariant 27a had no committed test:** `16b` is one, accepted and rejected cases with the exact error tokens.
4. **The invariant tracker omitted four of the thirty** (2, 10, 25, 27), and invariant 2's `hasTime` was optional.
5. **`net_requirements()` ignored a StockPolicy's eligibility filters** while the selector applied them.
6. **Guards could be bypassed:** the comma guard covered `upsert()` only, and a Role and three Measurements were created with commas through `POST`.
7. **Two scripts owned one validator.** `04` (the early spike) installed a negative-only `Measurement.onCreate`; `07` installs the full one; re-running `04` afterwards silently downgraded it. Found while deploying round-2 validators, when `24a` caught a unit-less Measurement being accepted. `04` now leaves an existing validator alone.
8. **README bug:** it never said to load `.env` into the shell, so every script raised `KeyError`.
9. **Reproducibility hygiene:** Neo4j was `latest` (now pinned), the compose port was fixed (`STRUCTR_PORT`), and `structr/license.key` is an intentionally empty bind-mount placeholder.
10. **Test fragility:** a demo asserted "the filter removes exactly 400 g" and failed as soon as other sealed stock existed. Eligibility demos now work out the expected exclusion independently (`mealplanner/fixtures.py`).

## Open items

Beyond the open rows above:

- **Chained recipes** (round 2 #6): a Plan whose Step 2 consumes Step 1's output double-counts material in `expected_combination_output`. Needs a material-flow model.
- **Reservation scaling** defaults an unset recipe yield to 1.
- **Variety scoring** treats an entry planned for the future as "just used" (days-ago goes negative, clamped to zero) and is global across MealPlans. Neither has been examined.
- **Invariants:** 12 deferred (9, 11, 15-24). Invariant 15 has **no enforcement at all**: an allocation of 500 g against 200 g on hand is accepted (`scripts/15e` shows it).
- **Duplication:** 14 scripts define their own `dt()`, and 39 define the same URL/user/password constants.
- **No test for most invariants** beyond the demo scripts, and the unit tests use a fake graph that could, in principle, render Structr differently from the real thing. `22a` re-checks the important cases against real Structr.

## Where a review would help most

1. **The model, §17 and §18.** Judgment calls, not derivations. Most worth an ontologist's challenge: J1 (`AcquisitionList` as one shared pool), J2 (nearest policy owns the stock), J5 (deriving "final output"), J6/J10 (exclusion semantics, especially not extending upward), J7 (availability along the type tree), J9 (default precedence).
2. **Adversarial data** the fixtures don't contain. `tests/fakegraph.py` makes a new case cheap to write; `22a` shows building throwaway fixtures on a real instance.
3. **Whether the tests test what they say.** In particular: are there places an assertion restates the code rather than checking independently worked-out values?
4. **The schema helpers and validators.** `SchemaDriftError` refuses to reconcile; is there a legitimate migration path it makes too hard? The StructrScript validators are string-built Python, and one was once silently overwritten by another script.
5. **General code quality:** the duplication above, the script/module boundary (`11c` is both a library and a demo), error handling.

## Test-data convention

Illustrative and test instance data is name-prefixed `TEST -- `; curated vocabulary is not, and placeholder vocabulary values carry `[PLACEHOLDER -- not sourced from USDA/FDC yet]` in their names.

**Audited at the end of a from-scratch build:** 214 named entities, 128 `TEST`-marked and 86 unmarked. All 86 are vocabulary: `DomainType` (45), `TypeHierarchy` (13), `DefaultSpecification` (10) with the `QuantitySpecification` values they point at (10), `NutrientProfile` (3), and the meal-type `Concept`s and scheme (5). No instance data (recipes, portions, processes, measurements, meal plans) is unmarked, and every default value and profile carries the placeholder marker in its name. The step-6 worked example (`06b`-`06d`) does create unmarked instance data, but `15a` deletes it and `15c` rebuilds it as `TEST` data, so it exists unmarked only between those scripts.
