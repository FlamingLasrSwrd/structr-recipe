# Future work

**Status: a list, kept by Claude for the owner** (started 2026-10-26, when the owner asked for one).
Nothing here is started. Each item says where it came from. The owner decides what is next.

## Asked for

| Item | Asked | What it would take |
|---|---|---|
| **Imports from similar applications, Grocy first** | 2026-10-26 | Grocy's REST API or export: products as foods (matched to `data/vocabulary.toml`, or a new food to add), quantity units and their conversions as weights per item and densities, locations as storage conditions, stock entries as Purchase bookings (`mealplanner/pantry.py`), with their best-before dates once a printed date can be recorded (below), the shopping list, price history as `PriceObservation`s (J27, not built), and recipes as recipe files under `docs/recipe-copyright.md`. Then Mealie, Tandoor, Paprika and KitchenOwl exports, and schema.org `Recipe` data, the same way |
| **Fill in the missing facts of a recipe's steps** | 2026-10-26: "The missing facts need to be filled in" | **Built 2026-10-26** (data-model.md J35, `docs/recipe-format.md` "A step's facts"): a step's working and waiting minutes, the steps before it (`after`, P-Plan's `isPreceededBy`), a tool's heat (a temperature or a burner level) and the doneness of what it makes (words, and a temperature inside), and cut forms as mechanical methods. Substitutions too (J36, `docs/recipe-format.md` "What may stand in"), and a tool named by what it does, "broil or grill" (J37, "A tool named by what it does"). **Still to do:** a cook recording which substitute it used (`via_substitution`, invariant 18); and the owner's 53 recipes transcribed again for the new facts, facts only, from their sources, which this repository does not hold. A recipe already cooked takes its facts as a new `version` |
| **Instructions written from the steps** | 2026-10-26 | **Built 2026-10-26**: the recipe page's "How to make it", each step one sentence of our own from its facts (`mealplanner/instructions.py`, `pages/lib/75_instructions.js`, `docs/recipe-format.md`); the two writers are compared word for word by `tools/check_instructions.py` and every recipe page by `tools/check_pages.py`. They read better as the recipes gain their facts (above) |
| **A basic set of recipes with the repository, and common ingredients and tools** | 2026-10-31: "Find some recipes that can be included as a basic set along with the git project"; "do a search for common recipe ingredients ... Do the same with common kitchen tools" | **Built 2026-10-31**: 20 recipes from NIH NHLBI recipe books (US government works) in `data/recipes/`, loaded only when asked for (`docs/recipe-format.md`, "The basic recipe set"); 77 foods and 20 kitchen tools added to `data/vocabulary.toml`, chosen from what the recipes need and from published studies of how often an ingredient appears in recipes, each food matched to an FDC record. **Open:** the matches are Claude's, for the owner to review, as the vocabulary's always are (J19) |
| **Releasing it for self-hosting** | 2026-10-24 | `docs/self-hosting.md`: written, not started, at the owner's word |
| **The Structr features this project does not use** | 2026-10-27: "work on implementing these features in this project" | A guide to Structr for AI use (`docs/structr-reference.md`), the features and the spikes' findings (`docs/structr-features.md`, `tools/spikes/`), and six batches to adopt them (its §5). **Being built** in that order; each batch's owner steps are added below as it lands |

## Offered, waiting on the owner

| Item | Offered | What it would take |
|---|---|---|
| Batches 5 and 6 of the Structr features | 2026-10-27 | `docs/structr-features.md` §5: declared parameters and GET for the Structr methods (it changes how every caller calls them, and 7.1 does not need it after all: the owner's word, 2026-10-31, is that it waits for the architecture decision), and a recipe's import as one transaction (a spike of nested creation, or a redesign of the importer, after measuring where an import's time goes) |
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
| The first capabilities, reviewed | 2026-10-26 | Oven heat, Broiler heat and Puréeing, and which tools give each, were chosen by Claude from the alternatives the HelloFresh recipes gave (J24 item 3); more as recipes need them (`data/vocabulary.toml`) |
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
| **The planner reads one consistent snapshot** | #14 | `extract.build_problem` reads through a `ReadCache` and searches in memory, but its reads are many requests, so a write during them could be half seen. One server-side read, or a check that nothing changed between the first read and the last |
| **`check_bookings.py` sweeps what an interrupted run left** | #7 | The development instance holds about 20 time regions and a few nodes from earlier interrupted checks; the check removes only what it made itself |

## For the owner to do

- ~~Upgrade your instance to Structr 7.1.0~~ **Done 2026-10-27**: backed up first (`2026-10-27_152625`),
  dry-run (one change: a label on 58 schema nodes), then upgraded; the graph kept its 42,386 nodes and
  88,680 relationships and `check_pages` found no difference. To go back, restore that backup with
  `docker-compose.yml`'s Structr image set to `structr/structr:6.0.0` (`docs/backups.md`). The steps
  below run on 7.1.0; each was checked there.
- If you use the cloud environment: paste `cloud/setup.sh` again into its "Setup script" field at
  claude.ai/code. It now pulls Structr 7.1.0 ahead of time (2026-10-27), and since 2026-10-31 it starts
  Docker itself when `service docker start` fails (it did in that session) and tries a refused pull
  again, so the images are there when a session starts. `cloud/bootstrap.sh` does the same in a
  session, which needs no pasting.

- Decide the wording of hard rule 2 (`docs/CLAUDE.md`): it says a trait added to a populated type is
  "only fixable with direct Cypher", but Structr's `createLabels` maintenance command fixes it through
  REST (spiked 2026-10-27, `docs/structr-features.md` §3). The rule still holds as a rule: adding a
  trait to a populated type needs that extra step.

- **Move your instance's tools onto their own account** (built 2026-10-31, at your word): the tools and
  scripts now log in as `mealplanner-tools`, an admin account, not as the superuser, so a wrong password
  in `.env` can no longer lock the superuser and the admin interface out for 15 minutes. Until these
  three steps, every tool answers 401 on your instance:
  1. `bash cloud/bootstrap.sh --env-only` adds a generated `STRUCTR_TOOLS_PASSWORD` to `.env` and
     changes nothing else in it.
  2. With your stack up, `STRUCTR_URL=http://localhost:8085 python3 tools/create_tools_user.py` makes
     the account (the one step that still uses the superuser). It changes no data, and what the
     account creates has no owner, as when the superuser made it. Run it again whenever the account
     is locked: more than four wrong passwords in a row lock it until this tool clears them.
  3. The development stack gets the account from its next `tools/rebuild.sh`, or the same command
     with port 8083.
- **Retire `resolveDefault` on your instance** (built 2026-10-31, at your word; after the account
  above): `STRUCTR_URL=http://localhost:8085 python3 scripts/47a_retire_resolve_default.py`, then
  restart Structr (`tools/owner_stack.sh stop`, then `up`). It deletes the StructrScript method
  `DomainType.resolveDefault`, which nothing calls, and changes no data. Run again, it finds nothing.
- **Turn on the pre-push hook in your clone** (built 2026-10-31, at your word): `git config
  core.hooksPath .githooks`, once. After that `git push` runs both interpreters' suites (`.venv` for the
  one with OR-tools), `tools/check_names.py` and `scripts/23a_schema_drift_test.py` first, about a
  minute, and stops on a failure; `git push --no-verify` skips it when you mean to.
- **Close Structr's initial `admin` account on your instance** (built 2026-10-31, your choice (a)): a fresh
  7.1.0 database is given a user `admin` with the password `admin` and full admin rights, and it logs in.
  `docker-compose.yml` now stops new databases from getting one; for yours, after the tools' account
  above, `STRUCTR_URL=http://localhost:8085 python3 scripts/48a_remove_initial_admin.py`. It deletes
  `admin` only if `admin`/`admin` still signs in; if you changed its password, it keeps it, says so,
  and takes its one failed sign-in back off its count. Whether your instance (first built on 6.0.0)
  has one was not checked.
- **Import the vocabulary's new foods and tools into your instance** (built 2026-10-31, at your word):
  `STRUCTR_URL=http://localhost:8085 python3 tools/import_vocabulary.py`. It adds 77 foods and 20 kitchen
  tools, and gives 12 foods you have a figure from their own FDC record: a density to 11 (Pecans, Powdered
  sugar, Carrot, Basil, Kale, Diced tomatoes (canned), Chickpeas (canned drained), Green and Red bell
  pepper, Tomato, Bok choy and napa cabbage) and a weight per chop (170 g) to Boneless pork chops (raw).
  The recipes using those 12 are worked out again, and a figure that rested on an unconvertible cup or
  chop may become known. On the development stack the whole vocabulary took 49 minutes
  from empty; yours holds most of it already. Then, if you want the basic recipes,
  `STRUCTR_URL=http://localhost:8085 python3 tools/import_recipe.py --check data/recipes/*.toml` lists
  what they would add and the tools your kitchen lacks, and the same without `--check` asks before
  loading one your kitchen cannot make. Worth reviewing in `data/vocabulary.toml` (the block headed
  "added 2026-10-31"): the FDC record each new food is matched to, and the new foods with no FoodKeeper
  shelf life.
- Sign in as Elijah and press one booking button: page bookings for a signed-in household member are
  untested (`docs/pages.md`).
- Copy `~/mealplanner-backups` off this machine now and then (`docs/backups.md`).
- ~~Bring your instance up to date: migrations 40a to 46a, the vocabulary, the pages and the methods~~
  **Done 2026-10-27**, on 7.1.0: the seven migrations in order (44a found no shared target, 45a no
  negative quantity, 46a no stored node breaking its rule among 8,022 quantities, 43 measurements, 1,726
  specifications and 56 planning constraints), one restart, then `import_vocabulary.py` (269 created,
  9 changed; the 55 recipes using the 5 changed foods worked out again, every figure unchanged),
  `install_pages.py` and `install_methods.py`. After it, `check_pages` found no difference, through the
  methods too, and `check_instructions` none in 1,145 sentences.
- Decide whether Structr should refuse a delete that leaves a meal entry, a substitution rule, a
  default or a reservation breaking its rule (`docs/structr-features.md` §5, batch 4). Today those four
  rules are checked only as a node is made. Checking them on every change too would make Structr
  refuse, for example, deleting a recipe version a planned meal still names, and some deletes (the
  reset script's, the owner instance's purge) would first need to run in another order.
