# Review guide

A solo, AI-assisted build of a BFO-grounded meal-planning data model on Structr 6.x/Neo4j, and of the
planner and pages that run on it. Three external code reviews have read it: the first commit `0cc20f1`,
the second `e8d1cbf`, the third the repository as of `523fc97` (2026-10-26). This guide says what became
of every finding, what our own audits found on top, what was built between the reviews, and what is
still open. It is ready for a fourth.

**The history was rewritten on 2026-10-26** to take personal information out of it (the owner's
decision): on `main`, every commit from "Add dietary and kitchen profiles" (2026-09-27, now `f58049f`) on
has a new id, and so has every commit of the unmerged branch `claude/laughing-maxwell-8yaern`. The
commits of the first two reviews and of their fixes kept theirs, and the ids this guide cites are the
new ones.

Nothing here asks you to trust a claim. Every "fixed" names the code and a test you can run, and every
"open" says why it is open. Where a review was found to be wrong or overstated, that is stated too,
with the evidence.

## What changed since the second review

91 commits since the second review's fixes (`29b41cc`), most of them in answer to the owner's
requests once the model met real recipes and a real household. In order of how much review they need:

- **The planner** (`mealplanner/planning/`, `docs/optimizer-design.md` §12, unreviewed): a week chosen
  as a whole, so a hard nutritional minimum is a constraint on a day's total (round 2 #21). A
  dependency-free exact search, a beam search and a climb, with an optional CP-SAT adapter, in one
  time-bounded portfolio; a household's week with a portion per person; a shortlist for a large recipe
  book; a whole run's time budget. Then, at the owner's requests: recipes asked for (from the week file
  and from a recipe page, kept over hard targets with advice on what the week misses), meal-prep
  sessions, an optional weight on the week's cooking time, a soft repeat tolerance, and re-planning a
  week under way (§12 records each, and each change to the objective).
- **The model, Rev 4.5:** people, households and shared meals (`docs/data-model.md` §19, which reverses
  the old "single-user" scope), and §18's J19 to J34: real recipes, stored nutrition per serving (J28,
  a knowing exception to "compute, don't store"), USDA retention factors (J30), USDA FoodKeeper shelf
  lives (J31), requests kept on a week (J33), and a menu changed as the week goes (J34).
- **Pages** (`pages/`, `docs/pages.md`): the week, the recipe book, a recipe, a week's nutrition, the
  pantry and the shopping list, as server-side JavaScript in Structr. They work out what they show
  function by function as the Python does, and `tools/check_pages.py` compares the two. Some pages also
  write: pantry bookings, "Mark cooked", skipping a meal, asking for a recipe next week;
  `tools/check_bookings.py` compares those writes with Python's own, field by field.
- **The pantry** (`mealplanner/pantry.py`, `docs/pantry.md`): Grocy-like bookings of stock in and out,
  written as the model's own processes, measurements and allocations.
- **Real data and operations:** a sourced food vocabulary (USDA FoodData Central), dietary, kitchen and
  pantry profiles, public prices; the owner's data in its own instance, out of reach of the demos
  (`tools/owner_stack.sh`); memory caps after the 8 GB laptop froze; backups of that instance, checked
  by restoring them (`tools/backup.py`, `docs/backups.md`).
- **Testing:** 814 offline tests (72 when the second review's fixes landed), two mutation sweeps
  (below), and checks of the pages against Python on real Structr.

## What is being reviewed

- **Correctness of the computations** (`mealplanner/`): inventory and expiry, unit conversion, default
  resolution, reservation and the shopping list, nutrition scoping, stock-policy resolution, exclusions,
  the pantry's bookings, the menu's changes.
- **The planner** (`mealplanner/planning/`), against `docs/optimizer-design.md`.
- **The pages** (`pages/`): whether they say what the Python says, and whether what they write is what
  the Python would write.
- **The Structr client and schema helpers** (`structr_client/`).
- **The model** (`docs/data-model.md`), especially §17 to §19, which record resolutions chosen under
  implementation pressure rather than derived.
- **Whether the repo is honest about itself:** does a fresh build reproduce what it claims, do the tests
  test what they say, do the documents agree with the code.

Start with `docs/CLAUDE.md` (document authority and hard rules), then this file. The two
`docs/design-review-document*.md` files are historical and describe the model *before* their own fixes.

## Deliberately out of scope

`docs/CLAUDE.md` lists what was considered and declined (no per-serving customization, no freeze/thaw
state, no non-linear scaling, free-text shelf location, no OWL reasoning). Two scope choices changed
since the second review: **Person and households are in** (the owner's decision, 2026-09-28), and
**there is a planner**.

**Security is out of scope by the owner's choice** ("local behind a firewall, I don't need security at
the moment", 2026-10-23), and it shows. The pages write as the superuser for anyone signed in
(`$.doPrivileged`), a write is a link with a token rather than a form post, the sign-in page is public,
and every node is visible to every signed-in user. Two consequences the firewall does not cover were
written down on 2026-10-26: Structr's port is published on every interface, so the whole home network
reaches it, and since a booking's token is not tied to the session, a page on another site could book
through a signed-in browser. `docs/self-hosting.md` says both, ranks what a release would need (step 4),
and weighs the security of each way of giving the pages one backend. Findings here are welcome, but they
describe a known posture rather than a regression.

## Running it

```bash
python3 -m unittest discover -s tests -t .            # 814 offline tests, no Structr (29 skip without OR-tools)
.venv/bin/python -m unittest discover -s tests -t .   # the same with OR-tools (requirements-solver.txt)
python3 tools/check_names.py                          # undefined names and unused imports (no pyflakes here)
python3 scripts/23a_schema_drift_test.py              # offline: the schema helpers against a drifted schema

cp .env.example .env && docker compose up -d
bash tools/rebuild.sh            # every script in build order, then the snapshot check: SNAPSHOT IDENTICAL
```

The offline tests run locally before each push. They ran on every push through a GitHub workflow until
2026-10-24, when the owner had it removed. Its name check and schema-drift test were not part of the
local run then, and the name check failed unnoticed for eight pushes (own audit 20 below); both are
run locally now.

**Verified from scratch (2026-10-26).** On fresh containers and volumes `tools/rebuild.sh` ran all 61
scripts in 567 s, none failing, and printed `SNAPSHOT IDENTICAL`, and again after Path S's schema
script `40a` (all 62 in 657 s): 219 named entities and 200 schema entries (every type, property, relationship and view, and the full source of every validator), the
same as `tools/expected_state.json`. On that build `tools/check_pages.py` found 0 differences, and
`tools/check_bookings.py` found every booking the same through the pages as through Python (buy, use,
count, open, move, discard, a cook, a recipe asked for, a menu changed and undone). On the owner's
instance `check_pages` found 0 differences on a committed week of 21 meals and 448 target groups, 53
recipes and 43 pantry portions, and so did a backup of it restored into a throwaway stack. Only the
maintainer's environment has been tested (Linux, Docker, Structr 6.0.0, Neo4j 2025.12.1). The schema
is in the snapshot because a validator is a method and can be silently replaced, which is what script
`04` once did to script `07`'s. `tools/expected_state.json` is a golden file: if a script's output
changes on purpose, regenerate it and read the diff.

**After round 3's fixes (2026-10-26)** the pages were installed on the development instance, and
`check_bookings` found every booking the same, bookings sent at once included, and `check_pages` 0
differences. The rebuild was not repeated: the fixes change the pages and the tools, not a script, and
no script installs the pages. The owner's instance has the new pages once `tools/install_pages.py` is
run against it.

## Round 3: the review of `523fc97`

An "adversarial review" in seven sections: findings ranked P0 and P1, over-engineering, further gaps,
alternative architectures, testing and operations, and an order of work. It did not run the stack, and
said so. Numbered here in the order the review raises them. Each was checked against the code first.
The fix for #9, the review's first in its order of work, is commit `38e8e62`; the documents and the
rest are the commit after it.

| # | Finding | Status |
|---|---|---|
| 1 | P0: not safe for untrusted users (superuser writes, links not form posts, a public sign-in page, every node visible to every signed-in user) | **Agreed, and known:** out of scope by the owner's choice (above). It is the review's reading of this guide's own list. `docs/self-hosting.md` step 4 is what a release needs |
| 2 | P1: the planner does not do all it is said to: "minimize waste" is a reward for using stock near expiry, not a penalty for what goes unused; stock is soft; cost is reported, not optimized | **Right about one document.** `docs/CLAUDE.md` said the tool "generates a weekly plan satisfying ... minimal ingredient waste"; it now says what the planner is meant to do and what it does, term by term (`optimizer-design.md` §12 already did, and this guide's open items listed all three). The objective is the owner's to change: a waste penalty, a cost term and weeks to judge the objective by are in `docs/todo.md` |
| 3 | P1: the documents' authority is out of step with the code: `docs/CLAUDE.md` single-user, without Person/Agent, "the optimizer has never been designed", Rev 4.2; the README two reviews | **Wrong about the commit it reviewed.** Every one of those quotes is from `e8d1cbf`, the second review's commit (`git show e8d1cbf:docs/CLAUDE.md`, lines 7, 13, 44, 52), as are the "44 scripts" and "214 named entities" it cites from this guide. At `523fc97` `docs/CLAUDE.md` says Rev 4.5, households, Person/Agent in, and the optimizer built; `tests/test_docs.py` has failed on a wrong revision since round 2 #22. The README's "two" was right then, a third review not having happened. **One it did not name was real:** the build sketch, marked authoritative, opened "Maps the Rev. 4.1 data model"; it now says what it covers. `tests/test_docs.py` now also fails if the README's or `docs/CLAUDE.md`'s count of reviews differs from the rounds recorded here, if the sketch names another revision than the model's, or if this guide's count of offline tests is not the real one |
| 4 | P1: the model says more than the build enforces; the documents should tell represented, computed, validated and enforced apart | **Already so where it was asked, now said in the model too.** `mealplanner/domain_invariants.py` records each invariant as structural, write-time, computation or audit, partial, deferred or not built, a test checks it covers all thirty, and the README counts each kind. The model's §11 listed the rules without saying so; it now says they are the model's, and where the build stands |
| 5 | The pages repeat the Python in JavaScript: two sources of truth | **Agreed, open** (this guide's open items). One backend for the pages is in `docs/todo.md`; the parity checks stay until the JavaScript is gone |
| 6 | The StructrScript `resolveDefault` disagrees with `mealplanner/defaults.py` | **Known** (round 2 #5: nothing calls it). Removing it is a schema change, run on the owner's instance too: in `docs/todo.md` |
| 7 | The build workflow is heavy (61 scripts, about 9½ minutes) and couples demos, migrations and setup | **Mostly as asked already.** Demos and checks remove what they make (test-data convention below), a schema migration for an existing instance is a numbered script declaring `owner_data_ok` and run there too (`CLAUDE.md`), and the owner's instance is never rebuilt. Found answering it: the development instance had about 20 nodes from earlier interrupted runs of `tools/check_bookings.py`, which removes only what it made itself; a sweep is in `docs/todo.md` |
| 8 | The pantry does not keep a history of storage: opening and moving are not dated, thawing does not restart the clock, and an estimated expiry feeds the planner | **Known** (`docs/pantry.md`, model J12). The page now heads the column "Expires (estimate)" and says under the table what the estimate rests on and what it leaves out (`pages/pantry.js`). A dated history reverses a scope decision (freezing and thawing are not modeled transitions): `docs/todo.md` |
| 9 | A page's write becomes visible about 0.3 s after the page answers; two quick presses can make two nodes of one name; check-then-create is not idempotent at once; confirm only after the write | **Right, and worse than stated; fixed** (`38e8e62`). Reproduced first on the development instance: one purchase form sent four times at once made four Processes of one name and every page said "booked"; two recipes asked for in one week at once made two MealPlans of one name; and the first try showed a commit refused (a unique name taken) after the page had said "booked". Each booking now runs in a transaction of its own that first writes to one lock node, so the next waits for its commit and then finds what it made, and the page answers once its booking is saved; a booking that fails is undone whole and said (`pages/common.js`, `docs/pages.md`; what Structr does is in `docs/structr-cheatsheet.md`). `tools/check_bookings.py` now sends bookings at once and reads without waiting: against the earlier pages it reports all three problems, against these all the same, and a booking by a signed-in user who is not the superuser was booked once, as the superuser. **Open:** a booking from the terminal (Python) is not serialized with one from a page |
| 10 | Leftovers are not stock; no journal or undo | **Known, open** (`docs/pantry.md`; invariants 23, 24, 27). `docs/todo.md` |
| 11 | The recipe model serves planning better than cooking: no step times, heat, doneness, alternatives, purchase forms; "to taste" optional; a discarded marinade counted as eaten | **Known, open** (model J20, J24; this guide's open items). The facts a step still lacks are on the owner's list (`docs/todo.md`), facts only (`docs/recipe-copyright.md`). **Since then (2026-10-26):** a step's times, order, heat and doneness (J35), what may stand in for an ingredient (J36) and a tool named by what it does (J37) are built; purchase forms, "to taste" and discarded material are still open |
| 12 | Nutrition and cost need clear uncertainty: estimates and unknowns visible; cost a floor | **Mostly so.** A hard target is never decided on an unknown, placeholder or unmarked figure (J15); the planner's report names each recipe whose figures rest on estimates (J21); a recipe page gives each figure's source; a day with an unknown figure is "indeterminate", never met; a cost is called a floor. **Open:** the nutrition page does not mark a total that rests on estimates (`docs/todo.md`) |
| 13 | Alternatives: a smaller application model mapped to BFO, PostgreSQL with an append-only ledger, maintained projections, one solver | **Noted.** The review recommends none of them now, and neither do we; BFO is already design discipline, not a runtime dependency (`docs/CLAUDE.md`). The owner's call if the project becomes a product |
| 14 | Batch the planner's reads into one snapshot and compute in memory; 95 requests and 3.1 s for a small run | **Partly a mix-up.** The 95 requests are the per-slot selector's (round 2 #15). The planner already reads the week once through a `ReadCache` and searches in memory (`planning/extract.py`). It is right that those reads are many requests, not one consistent snapshot, so a write during them could be half seen: `docs/todo.md` |
| 15 | Restore automated checks: the offline suite, the name check and the schema-drift test, OR-tools in its own job, a slow integration job | **Declined for GitHub by the owner** (2026-10-24: GitHub runs nothing). The point that a check should not rest on remembering stands: a git pre-push hook running the same is offered in `docs/todo.md` |
| 16 | Backups: restore onto a real instance untested; copies on the same disk | **Partly.** `verify` restores every backup it checks into a real throwaway stack with the same code `restore` uses to load it (`put_back`), and the first was verified so (above). What has run only against faked Docker is `restore`'s sequence around that: the safety backup, stopping the owner's stack, starting it again. Copying backups off the machine is the owner's to-do (`docs/backups.md`) |

**Where the review was wrong:** #3's quotes, from an older commit than the one it reviewed, and #14's
request count, the selector's. **Where it was right and worse than stated:** #9.

## Round 2: the review of `e8d1cbf`

24 numbered points. Each was checked against the code and the live data first. The fixes are in commit `29b41cc`. Rows 6, 15, 16 and 17 were open then; commit `c7256f1` fixed or decided them, and their rows below say so. Row 21 (hard minimums) and round 1 #24 (placeholder nutrient data) are addressed by commit `123bea7`, the planner; their rows say what is and is not built.

| # | Finding | Status |
|---|---|---|
| 1 | `current_magnitude` used measurements and processes from the future | **Fixed.** Bounded by `now` for the baseline and for consumption; `instance_expiration` too. `tests/test_inventory.py`. The old code reproduces all three symptoms (420 g instead of 500, a not-yet-happened process already consuming) |
| 2 | Allocation quantities subtracted without unit conversion | **Fixed.** Everything is converted to grams first; an unusable quantity raises `QuantityError` instead of counting as zero. The old code said a 0.5 kg baseline minus 100 g left **-99.5 g**. Measurements now need a unit at write time. `expected_combination_output` had the same flaw and is fixed too |
| 3 | Reservation keyed to the candidate type, not the stock pool | **Fixed, with a correction.** The review's concrete example does not occur (the selector computes eligibility at the ingredient's own type, so a turkey recipe never sees chicken's stock). The underlying scope mismatch was real in both directions, though: a generic "Poultry" demand ignored a chicken reservation, and vice versa. Availability is now computed along the type tree (model §18 J7). Unit tests plus a live check in `22a` |
| 4 | `StockPolicy` target/threshold compared without units | **Fixed.** Write-time rule: same unit. `24a` |
| 5 | `resolveDefault` ignores `keyedBy` | **Fixed.** Resolved in Python by (kind, keys) with defined precedence (`mealplanner/defaults.py`, §18 J9), used for yields, shelf lives, densities and mass-per-unit. The StructrScript method remains, kind-only, and nothing in `mealplanner/` calls it |
| 6 | `expected_combination_output` is dead code and can't handle chained recipes | **Half wrong, half fixed.** "Dead code" was my own stale docstring; `15c` has used it to compute recipe outputs for a while, and the docstring is corrected. The chained-recipe point was right and is **fixed** (§18 J11): material is routed through the Steps, an intermediate is taken up by the Step that consumes it, and only terminal Steps are summed. The hand-worked chain (boil 100 g dry pasta x2.0, toss with 20 g butter) is 200 g; the old code said 400 g. Flow that can't be traced (an intermediate split between Steps with no stated shares, a cycle) raises rather than guessing. `tests/test_material_flow.py`, and a live check in `25a` |
| 7 | Exclusions inspect instruments, outputs and optional inputs as ingredients | **Fixed** (§18 J10): non-optional inputs and outputs count; instruments never; an optional excluded input is reported so it can be left out. Unit tests, and a live check in `22a` |
| 8 | `Measurement.hasTime` required but not enforced | **Fixed.** `notNull`, migrated on the live instance by `07` (the drift-detecting helper refused the new declaration until it ran, which is what it is for) |
| 9 | Range quantities bypass the negative check | **Fixed, and it was wider than reported:** a `QuantitySpecification`'s scalar value had no negative check either. `24a` |
| 10 | Zero treated as missing (`or` defaults) | **Fixed** in the selector (a zero weight became 0.5, a zero time budget became 60 and would have divided by zero), and in the yield and servings readers. A related sort bug (`score or -1` ranked a 0 below a negative) is fixed. `tests/test_selector.py` |
| 11 | `upsert()` patches the first of several matches | **Fixed.** `DuplicateMatchError`; writes nothing |
| 12 | Unsafe-character guard incomplete | **Fixed.** One `validate_exact_match_value` for comma and semicolon, applied to POST, PATCH and upsert. The semicolon behaviour comes from Structr's documentation; I did not reproduce it |
| 13 | `wait_until_ready` hides authentication errors | **Fixed.** Retries connection errors, timeouts and 5xx; any other HTTP error fails immediately. A real cold boot passes |
| 14 | No request timeout | **Fixed.** Default (5 s connect, 120 s read), configurable |
| 15 | N+1 REST traversal | **Reduced, not solved.** One selector run over 4 recipes and 17 stock portions made 303 HTTP requests (19 s) at review time and **95 (3.1 s)** now, with the same ranking. After the inventory refactor it was 260, only 112 of them distinct, so the read-only entry points (`select`, `net_requirements`, `nutrition_report`, `find_overdraws`) run over a `structr_client.ReadCache`, which fetches each node, listing and query once and cannot write. Cost is still linear in the amount of stock and history, because the on-hand scan visits every portion ever recorded; a real fix bounds that scan or moves it server-side. Found on the way: `get_all(type)` returned only Structr's default page and said nothing about the rest, so a large type was silently truncated. It now reads every page (`tests/test_client.py`, live check in `25a`) |
| 16 | Same-instant events are undecidable (`>=`) | **Decided** (§18 J8). A Process at the exact instant of a weighing counts as consuming, i.e. the weighing is read as taken before it. Nothing recorded says which came first, and overstating stock is the costlier error. This deviates from §4.1.1 ("after") on purpose, and a strict reading would need the model to carry the order. The test pins it. You may disagree with the direction |
| 17 | Expiry anchored to the latest weighing, not a Purchase Process | **Fixed** (§18 J12). The clock starts at the Process the portion `begins_to_exist_during` (the model's purchase or cook), else at the **earliest** weighing; reweighing no longer restarts it. The old code said 4 days left where 2 is right in the review's own shape of case. **Open:** a portion divided off a larger one restarts the clock at the division (no parent link in the model), and the time of *opening* is not modeled. `tests/test_inventory.py`, live check in `25a` |
| 18 | "No container" means two different things | **Open, needs a decision** |
| 19 | Nested StockPolicies double-count stock | **Fixed:** the nearest policy owns the physical stock (§18 J2). Unit test plus a live check |
| 20 | Soft `ExclusionConstraint`s do nothing | **Fixed:** a soft exclusion costs the candidate its weight (§18 J10) |
| 21 | Greedy selection can't enforce hard minimums | **Built, unreviewed.** A per-slot selector cannot meet a hard minimum: `docs/optimizer-design.md` §2 shows it on a 3-slot day run against the real scoring functions (greedy reaches 36 g against 70 g while 63 of 125 menus are feasible, and no one-slot swap repairs it). The planner (`mealplanner/planning/`, `plan_week`) chooses the week as a whole, so a minimum is a constraint on the day's final total; when none can be met it returns the closest plan and the exact shortfall instead. Verified offline (hand-worked cases, an independent brute-force oracle over 80 random problems, bound-soundness checks, and score equality with the selector for a single slot) and against real Structr (`scripts/26a`, which confirms the committed day with `nutrition_report`). **Limits:** a full week's plan is not proven optimal (the search says so). An optional CP-SAT adapter (OR-tools) was added and agrees with the brute-force oracle, but measured on synthetic weeks it does not prove full weeks either: it and the dependency-free search each prove some weeks the other cannot, and neither proves a 21-slot, 30-recipe week (§12). The objective is a proposal (§4.5). The selector itself is unchanged and still only scores a minimum |
| 22 | Documents drift from each other and the code | **Partly fixed.** `CLAUDE.md` said Rev 4.2 while the model was 4.3. Now `tests/test_docs.py` fails if the revision, the structural-type count, or the invariant tracker's coverage disagree with the code. There is still no machine-readable manifest |
| 23 | "~35" vs 50 structural types | **Fixed, and the fix was itself wrong first.** I copied "50" from a comment in `structural_types.py`; the new test showed the real count is **51** (`ExclusionConstraint` was added after that comment was written). All three places corrected |
| 24 | Not enough automated tests | **Fixed in part:** an offline suite over the pure logic (`tests/`, no Structr), counted under Running it, run before each push (by CI until 2026-10-24), and two mutation sweeps (own audits 19 and 25). It covers the review's own list: future events, mixed units, zero values, optional ingredients, subtype/supertype collisions, overlapping policies, multiple defaults, multiple outputs. Still missing: most invariants have no test beyond the demo scripts |

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
| 6 | The selector isn't plan-level | **Addressed by the planner** (round 2 #21). The selector is unchanged and still greedy per slot |
| 7 | No reservation layer | **Partly fixed.** Raw-ingredient reservation and `net_requirements()` exist; leftover surplus (invariants 23/24) is not built |
| 8 | Expiry anchored to the latest measurement | **Fixed** (round 2 #17, §18 J12) |
| 9 | "No container" means two things | **Open** (round 2 #18) |
| 10 | First applicable StockPolicy wins | **Fixed** (§18 J2) |
| 11 | Exclusions one hop deep | **Fixed** (§18 J6). A type *above* an excluded one is not banned, which for allergies is a choice worth challenging |
| 12 | Required-type set loses multiplicity | **No change.** It feeds a set-membership check where multiplicity is irrelevant |
| 13 | Only the first output considered | **Fixed** (§18 J5) |
| 14 | Missing yield defaults to 1 serving | **Fixed.** Nutrition was already strict; reservation now is too: an entry for a recipe with no yield in servings raises `QuantityError` naming the entry (§18 J13), and the lenient reader is deleted |
| 15 | Difficulty authored or derived? | **Open** |
| 16 | `Function` is unused | **Open** |
| 17 | Numeric truthiness (`or 1.0`) | **Underrated at the time.** I judged the sites I looked at harmless because invariant 14 forbids a zero yield; round 2 #10 then showed the selector's `or` defaults were real bugs. All are now explicit `is None` checks |
| 18 | Same-instant events | **Decided** (round 2 #16, §18 J8) |
| 19, 20 | REST N+1 | **Reduced** (round 2 #15): 303 requests to 95 for the same run |
| 21 | Docs and code drift | **Partly fixed** (round 2 #22) |
| 22 | Invariant tracker needs states | **Partly.** It separates structural / write-time / computation / partial / deferred and covers all 30; `tests/test_docs.py` enforces the coverage |
| 23 | Test scripts leave state behind | **Partly fixed.** `16b`, `20a`, `21a`, `22a`, `24a` remove what they create. `15e` leaves its "Leftover test week" on purpose (`16b` builds on it); `08` and `09` leave everything until `15a` wipes it |
| 24 | Placeholder nutrient data can satisfy hard constraints | **Fixed for the planner** (§18 J15): `NutrientProfile.provenance`, and a hard target is never decided on a figure that is unknown, placeholder or unmarked. The owner's vocabulary is sourced from USDA FoodData Central, and by the owner's decision (J21) an estimated figure may decide a hard target and is reported as an estimate; a development build's demo figures stay placeholders. The selector still scores with placeholder figures, and only ever scores a hard minimum |
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
11. **`17c` hard-coded totals:** its expiry check asserted "750 g / 600 g" of chicken in stock and failed on any instance where other demos (`17d`, `18b`) had also left chicken, the same fragility as item 10. Found by re-running the demos on the working instance after the third round's changes; it now checks each of its own portions against values worked out from the constants.
12. **`dt()` took the first of several matches:** 14 scripts and 3 modules each had a copy that returned `[0]` of whatever matched (or raised `IndexError` on none). There is now one, in `mealplanner/typetree.py`, and it raises unless exactly one DomainType has the name.
13. **The planner demo's expected value was incomplete, and the planner was right.** `26a` first failed because its independent enumeration ignored leftovers: with the live "Cooked Leftover" default seeded, the planner found a better plan (cook the omelette once, eat it at lunch and dinner: 1.9 against 1.7). The enumeration now understands leftovers and the two cases are checked separately (`leftovers=False` and `True`).
14. **`12b` cannot be re-run on a built instance:** its second step names a type the early build creates and `15a` later replaces (already true before this round; it only ever ran once, in order). The provenance migration is therefore its own idempotent script, `12c`.
15. **No pyflakes:** a helper deleted while something still called it is a failure this project has had, so `tools/check_names.py` (undefined names, unused imports) now runs with the offline tests.
16. **The solver did not deliver what I recommended it for.** The design doc called a library solver "the real fix" for proving a full week optimal. Installed and measured, it is not: on the same synthetic weeks the dependency-free exact search proves some the solver cannot (0.2 s against 14.6 s on one), the solver proves others the exact search cannot, and neither proves a 21-slot, 30-recipe week, where all three methods find the same plan and CP-SAT's ceiling stays at the trivial one. `auto` is therefore a portfolio of both plus a beam search, not a swap.
17. **A large collection read returned its first page only.** Structr leaves `result_count` and `page_count` out of a big collection's response; `StructrClient.get_all` took a missing count to mean one page, so at 13,000 NutrientProfiles it returned 500, and the vocabulary import, finding nothing, created all 13,000 again. Found loading the HelloFresh recipes on a throwaway instance, before the owner's; the client now reads until a short page (`tests/test_client.py`, `docs/structr-cheatsheet.md`).
18. **A mean over repeated FDC ids counted each id once.** A spice blend written as parts (turmeric twice for 2:1) was loaded as equal parts, contradicting its own note; found when the live figures for one recipe disagreed with the independent calculation. Repeats now count (`vocabulary_import.composition`).

19. **Mutation sweeps found corners no test reached** (2026-10-23): each module's code was broken one change at a time and the tests run, and every change the tests did not notice became a test. They found two things the climb left open (`dd83f71`), the difficulty cap and three corners of the shortlist (`017dd37`), four of the stored recipe nutrition (`bbe298a`), five stock-allocation cases (`727302f`), hard rule 4 in the vocabulary import (`2806898`), CP-SAT offering a committed cook's leftovers only (`b81e0d5`), the nutrition report's other scopes and shares (`5acc157`), and the weights of a cup, a spoon and an egg (`9e78382`).
20. **The GitHub check failed for eight pushes before anyone looked.** `tools/check_names.py` found two unused imports in a test; the local run was the unit tests alone. The owner then had the workflow removed (2026-10-24), and the name check is run with the tests before each push.
21. **A page's write commits a moment after the page answers** (about 0.3 s, measured 2026-10-24): a read straight after it sees nothing. `tools/check_bookings.py` waits; a person reloading does not notice. Two presses within that moment could each make a node of one name, which the next read refuses. The third review ranked it first; it is fixed (round 3 #9 below).
22. **A day already eaten could block the rest of the week.** A hard target over meals all committed was judged like any other, so a past day that missed one left no feasible plan for what remained. Such a group is now settled, not judged, and said (`diagnose.settled`; optimizer-design §12). Found designing menu changes, before any week hit it.
23. **The development instance had drifted from the scripts:** it lacked the schema of `30a` to `37a`, so a check of the nutrition page there compared nothing against something (every recipe unknown on the page, worked out in Python). Found when the comparison disagreed on a recipe with figures; brought up to date and given stored figures, it agreed (2026-10-26).
24. **The first rule for where a loose portion is kept** dated flour, rice, cans and oil as if refrigerated, or not at all, and put garlic in the fridge. It is now where the food keeps longest unopened (J31, `inventory.assumed_storage`).
25. **A second mutation sweep, of the week's new code** (2026-10-26): 17 changes to the menu changes, the requests, the soft repeat tolerance, settled groups, the week totals, the step-name limit and the backups. 16 were caught; the 17th, CP-SAT's constant for a recipe only committed meals take past the tolerance, raised the ceiling without breaking "ceiling at least the optimum". A proven solve's ceiling is now required to equal the optimum (`tests/test_planning_repeats.py`).
26. **Backups named to the second collided** when two were made within one (a restore's safety backup right after another): found by the tests, fixed before first use.

## Open items

Beyond the open rows above:

- **Needs a model decision, not code:** round 2 #18 (does "no container" mean *loose* or *unknown*? For
  expiry a portion in none is now taken to be kept where its food keeps longest unopened, J31; §9's
  filter question stands); round 1 #15 (is difficulty authored or derived? the planner uses
  `difficultyRating` only as an optional hard cap) and #16 (`Function` is unused; `docs/todo.md` would
  use it for equipment named by what it does).
- **The planner is unreviewed.** It proves a small week optimal and returns a good, unproven plan for a
  full one (§12 has the measured limits). The objective is a proposal the owner tunes; §12 records each
  change made at the owner's request (requests kept over hard targets, the cooking-time weight, the soft
  repeat tolerance, settled groups) and the defaults taken without an answer. Not built: a tighter
  variety formulation or stock as flows for the solver, hard stock, a per-day time budget, a penalty for
  unused near-expiry stock, a soft difficulty term.
- **The pages duplicate the Python in JavaScript.** Each page follows a Python function by function,
  and `tools/check_pages.py` and `tools/check_bookings.py` compare them on real Structr; nothing makes a
  change to one side reach the other. A booking by a signed-in user who is not the superuser was checked
  on the development instance with a test account (round 3 #9); one through a browser, by a household
  member signed in as themselves, has not been made. Bookings from the pages run one at a time; one from
  the terminal is not serialized with them.
- **Security** is out of scope by choice (above).
- **Nutrition from ingredients** (J18): vitamins and minerals lose what USDA's retention table says
  (J30), every fat is kept (J32); vitamins D, E and K and added sugars have no factor and are counted
  whole. Fat gained in frying or lost in draining is not modeled.
- **Every figure names its source** (J21); foods FDC lacks use the nearest FDC food as a proxy, said so.
- **Real recipes** (J20, J24): seasoning "to taste" is optional, a discarded marinade is counted as
  eaten, sizes are Types, a step's alternative tools are a capability any of them gives (J37), purchase units
  are not modeled.
  Recipes keep facts only, never their source's instructions (`docs/recipe-copyright.md`), and a step
  records its method, inputs, output and equipment, and since 2026-10-26 may say its time, order, heat and doneness (J35)
  and what may stand in for an ingredient (J36) (`docs/todo.md`).
- **The pantry** (`docs/pantry.md`): an expiry is an estimate, and the page says so: thawing does not restart the clock, opening does not either, a
  printed best-before date cannot be recorded (invariant 2 reaches a Quality only), a cook's leftovers
  are not stock, and there is no journal to undo a booking.
- **Menu changes** (J34): leftovers of an earlier meal eaten instead have no form; the planner leaves a
  meal eaten instead out of its day.
- **Prices** (J27, `docs/prices.md`): interim public figures; spices, leaveners and the kits' sauces are
  unpriced, so a cost is a floor. Cost is reported, not optimized.
- **Backups** (`docs/backups.md`): every stop of the owner's stack makes one, and the first was verified
  by restoring it into a throwaway stack (same counts, every page the same). `restore` onto the owner's
  instance has run only against faked Docker. The copies sit on the same disk.
- **Scaling:** a week over 1,001 recipes reads in about four minutes and searches a shortlist (§12); the
  on-hand scan still reads every portion ever recorded, so cost grows with history.
- **Invariants:** 11 deferred (9, 11, 16-24) and 3 not built or uncheckable (10, 25, 27). Invariant 15
  is an audit, not a write-time check (`inventory.overdraws`). Leftover surplus (invariants 23, 24, 27)
  is not built; the planner plans leftovers within one MealPlan.
- **No test for most invariants** beyond the demo scripts, and the unit tests use a fake graph that
  could render Structr differently from the real thing. `22a`, `25a`, `26a`, `tools/check_pages.py` and
  `tools/check_bookings.py` re-check the important cases against real Structr.
- **Future work** the owner has asked for or been offered is listed in `docs/todo.md`.

## Where a review would help most

1. **The planner, `mealplanner/planning/` and `docs/optimizer-design.md`.** The objective (§4.5) and
   every change §12 records to it; whether a group of committed meals should be settled rather than
   judged; whether keeping a requested recipe over a hard target, with advice, is the right failure;
   whether the soft repeat tolerance and the cooking-time weight are scaled sensibly against terms that
   are per slot and per target-day; and whether a dependency-free search is enough.
2. **The model, §17 to §19.** Judgment calls, not derivations. Most worth an ontologist's challenge: J1
   (`AcquisitionList` as one shared pool), J2 (nearest policy owns the stock), J5 (deriving "final
   output"), J6/J10 (exclusion semantics), J7 (availability along the type tree), J9 (default
   precedence), J28 (storing a rollup), J33 (a request as a relationship on a week, not a constraint
   type), J34 (a meal not from the book as words on the meal it replaced).
3. **The pages' two implementations.** Whether `check_pages` and `check_bookings` compare enough to keep
   the JavaScript honest, and whether the bookings' idempotence by token holds.
4. **Whether the tests test what they say**, especially where an assertion might restate the code
   rather than check independently worked-out values.
5. **Adversarial data** the fixtures don't contain. `tests/fakegraph.py` makes a new case cheap to
   write; `22a` shows building throwaway fixtures on a real instance.
6. **The schema helpers and validators.** `SchemaDriftError` refuses to reconcile; is there a legitimate
   migration path it makes too hard? The StructrScript validators are string-built Python.
7. **The backup tool**, especially `restore`, which replaces the owner's data.
8. **General code quality:** the script/module boundary (`11c` is both a library and a demo), error
   handling, and the size of `mealplanner/planning/evaluate.py` and `cpsat.py`.

## Test-data convention

Illustrative and test instance data is name-prefixed `TEST -- `; curated vocabulary is not, and placeholder vocabulary values carry `[PLACEHOLDER -- not sourced from USDA/FDC yet]` in their names.

**Audited at the end of a from-scratch build (2026-10-26):** 219 named entities, 128 `TEST`-marked and 91 unmarked. All 91 are vocabulary: `DomainType` (45), `TypeHierarchy` (13), `DefaultSpecification` (11) with the `QuantitySpecification` values they point at (11), `NutrientProfile` (3), and the meal-type and identifier-scheme `Concept`s (6) and their schemes (2). No instance data (recipes, portions, processes, measurements, meal plans) is unmarked, and every default value and profile carries the placeholder marker in its name. The step-6 worked example (`06b`-`06d`) does create unmarked instance data, but `15a` deletes it and `15c` rebuilds it as `TEST` data, so it exists unmarked only between those scripts.
