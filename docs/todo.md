# Future work

**Status: a list, kept by Claude for the owner** (started 2026-10-26, when the owner asked for one).
Nothing here is started. Each item says where it came from. The owner decides what is next.

## Asked for

| Item | Asked | What it would take |
|---|---|---|
| **Imports from similar applications, Grocy first** | 2026-10-26 | Grocy's REST API or export: products as foods (matched to `data/vocabulary.toml`, or a new food to add), quantity units and their conversions as weights per item and densities, locations as storage conditions, stock entries as Purchase bookings (`mealplanner/pantry.py`), with their best-before dates once a printed date can be recorded (below), the shopping list, price history as `PriceObservation`s (J27, not built), and recipes as recipe files under `docs/recipe-copyright.md`. Then Mealie, Tandoor, Paprika and KitchenOwl exports, and schema.org `Recipe` data, the same way |
| **Fill in the missing facts of a recipe's steps** | 2026-10-26: "The missing facts need to be filled in" | A step records its method, its inputs and amounts, its output and its equipment (`docs/recipe-format.md`). Still missing, every one a fact (`docs/recipe-copyright.md`): (1) **time per step**, working and waiting: the model names step duration as a Transformation Method default (data-model.md §3's hierarchies), with a step's own value beside it; (2) **heat**: a burner's level and an oven's temperature, a `StateRequirement` on the instrument (built in the schema, `recipe_schema.py`, written by nothing); (3) **doneness and safe internal temperatures** ("until golden", 165 °F for poultry from FSIS's chart, public domain), a `StateRequirement` on the output; (4) **cut forms** (diced, minced, sliced): mechanical Transformation Methods, a branch the model names and the vocabulary does not load yet, with intermediate Types where it matters; (5) **equipment named by what it does** (a Function, "Heating"), which also answers alternatives within a step ("broil or grill", J24 item 3); (6) **substitutions**, `SubstitutionRule` (§5.3, in the schema, unused); (7) **an explicit step order**, P-Plan's `isPreceededBy`, so steps that run side by side can say so. Then the recipe format, the importer and the recipe page carry them, and the owner's 53 recipes are transcribed again for them, facts only. Check each against data-model.md first: none should need a new structural type (CLAUDE.md hard rule 3) |
| **Instructions written from the steps** | 2026-10-26 | The recipe page writes each step as plain sentences of its own from the facts above ("Sauté the onion, poblano, oil, spice blend, tomato and tomato paste in a saucepan until soft, about 5 minutes"). Our own wording, so no source's text is needed (`docs/recipe-copyright.md`) |
| **Releasing it for self-hosting** | 2026-10-24 | `docs/self-hosting.md`: written, not started, at the owner's word |

## Offered, waiting on the owner

| Item | Offered | What it would take |
|---|---|---|
| The cheap security fixes | 2026-10-26 | Structr's port bound to this machine unless other devices should reach it; bookings as form posts with a token tied to the session; HTTPS once phones connect (`docs/self-hosting.md` step 4, which says why a firewall does not cover them, and ranks the rest) |
| A "Plan the week" button and a preferences page | 2026-10-24, 2026-10-26 | A planner container watching the graph for a request to plan (self-hosting step 3); the week file's settings kept on the week's MealPlan and edited on a page |
| Weights that read as shares of the score | 2026-10-26 | Today each weight is per unit (per meal, per target and day, per hour), so a term's pull grows with how many units it has (`docs/optimizer-design.md` §4.5). Scaling each family by its count would let a preference say "nutrition matters twice as much as time". An objective change: the owner's call |
| Sharing reference data and recipes through a service | 2026-10-26 | Today: versioned files in the repository and idempotent importers. A hosted service needs either one multi-household instance with curated shared data (`docs/verification-and-sharing.md` §3.4, §3.6) or a catalogue that self-hosted instances pull releases from |
| Ticking a grocery item books a purchase | 2026-10-24 | The shopping page's tick opens a Buy prefilled with the list's amount, changed to the package's |
| A printed best-before date | 2026-10-23 | `Measurement -[IS_ABOUT]->` a Disposition as well as a Quality (invariant 2; `docs/pantry.md` finding 3): a schema change |
| Thawing restarts the clock | 2026-10-23 | A thawing Process from which a new portion begins: modelling thawing as a transformation, which §13 declined (`docs/pantry.md` finding 1) |
| A pantry journal, and undoing a booking | 2026-10-23 | `docs/pantry.md` item 6, with prices paid, minimum stock on the page and barcodes |
| Leftovers of an earlier meal eaten instead | 2026-10-24 | The week page's "ate instead" takes a recipe or words today (data-model.md J34) |
| A count, or a meal, for a recipe asked for from its page | 2026-10-24 | The week file still says "twice" or "on Wed Dinner" (J33) |
| A review of the FoodKeeper and retention matches | 2026-10-24 | Each food's product and each class's rows, for the owner to check (J30, J31) |

## From the third review (2026-10-26), waiting on the owner

What the review recommended that is more than a fix (`REVIEW.md` round 3 says what was fixed at once).

| Item | Review | What it would take |
|---|---|---|
| **One backend for what the pages compute and book** | #5 | What each way of doing it means for security is in `docs/self-hosting.md`. `docs/architecture-decision.md` proposes the platform for it. Today each page repeats a Python function in JavaScript, and `check_pages.py` and `check_bookings.py` compare the two. A small Python service beside Structr (the planner container of `docs/self-hosting.md` step 3) would answer the pages, so each computation and booking exists once; the checks stay until the JavaScript is gone. It would also let a booking from the terminal take the pages' lock (below) |
| **Bookings from the terminal one at a time with the pages'** | #9 | The pages' bookings are serialized by a lock node (`docs/pages.md`); `mealplanner/pantry.py`, `requests.py` and `menu_changes.py` write a REST request at a time and cannot hold it. Through the backend above, or a page endpoint the tools call |
| **Storage and opening as a history** | #8 | Opening, freezing and moving recorded as dated events, and shelf life worked out over the sequence of conditions. It reverses a scope decision (`docs/CLAUDE.md`: freezing and thawing are not modeled transitions) and overlaps "Thawing restarts the clock" above. Until then the pantry page says its expiry is an estimate and why |
| **A cook's leftovers as stock** | #10 | A cook books a leftover portion with its amount, origin, storage and expiry, which later meals and the next week's planner draw on (invariants 23, 24 and 27; `docs/pantry.md`). With "a pantry journal, and undoing a booking" above, as compensating bookings rather than edits |
| **Waste and cost in the objective** | #2 | A penalty for stock left to expire unused, and a cost term, each defined and tested on its own before the documents say the planner minimizes waste or spending. Objective changes: the owner's call (`docs/optimizer-design.md` §4.5) |
| **Weeks to judge the objective by** | #2 | Representative weeks, including ones where nutrition pulls against time, waste, repeats, cost or stock, with the owner's verdict on each plan, kept as fixtures the planner is checked against |
| **Retire the StructrScript `resolveDefault`** | #6 | A schema-only script removing the method (nothing calls it; `mealplanner/defaults.py` resolves by kind and keys), run on the owner's instance too, and the build sketch and cheatsheet brought along |
| **Checks that run themselves** | #15 | GitHub runs nothing (the owner's choice, 2026-10-24). A git pre-push hook in the repository, enabled with `git config core.hooksPath`, would run both interpreters' suites, `check_names.py` and `23a` before every push, so nothing rests on remembering |
| **The planner reads one consistent snapshot** | #14 | `extract.build_problem` reads through a `ReadCache` and searches in memory, but its reads are many requests, so a write during them could be half seen. One server-side read, or a check that nothing changed between the first read and the last |
| **The nutrition page marks totals that rest on estimates** | #12 | The planner's report names the recipes whose figures rest on estimates (J21) and a recipe page gives each figure's source; the week's nutrition page shows met, under, over or indeterminate without saying which totals rest on estimates. `nutrition_report` would say it too, so the page and the Python still agree |
| **`check_bookings.py` sweeps what an interrupted run left** | #7 | The development instance holds about 20 time regions and a few nodes from earlier interrupted checks; the check removes only what it made itself |

## For the owner to do

- Sign in as Elijah and press one booking button: page bookings for a signed-in household member are
  untested (`docs/pages.md`).
- Copy `~/mealplanner-backups` off this machine now and then (`docs/backups.md`).
- Bring your instance up to date (2026-10-26), with its stack up: the schema migration for the
  households' booking turns, a Structr restart, then the pages (their bookings now one at a time) and
  the methods:
  `STRUCTR_URL=http://localhost:8085 python3 scripts/40a_booking_lock_schema.py`, restart Structr
  (`bash tools/owner_stack.sh stop`, which also backs it up, then `bash tools/owner_stack.sh up`), then
  `STRUCTR_URL=http://localhost:8085 python3 tools/install_pages.py` and
  `STRUCTR_URL=http://localhost:8085 python3 tools/install_methods.py`.
