# Work split into sessions

**Status: a plan, kept by Claude for the owner** (2026-11-04, at the owner's request: "Construct a plan
from the todo list items for new sessions to work on"). It takes the items of `todo.md` that a session
can do without a decision only the owner can make, and groups them so that sessions running at the
same time never edit the same files. `todo.md` stays the list; this says who does what, in which order.
When a session's work lands, it marks its item in `todo.md` and its row here.

## Rules every session follows

- Read `CLAUDE.md` and `docs/CLAUDE.md` first. Commit and push each verified batch on a branch of its
  own (a worktree), never `main`; the owner merges.
- **A live check runs on a throwaway stack of the session's own**, never the development stack (8083)
  and never the owner's (8085): `COMPOSE_PROJECT_NAME=<session's project> STRUCTR_PORT=<port> bash
  cloud/bootstrap.sh`, then `STRUCTR_URL=http://localhost:<port> bash tools/rebuild.sh` (its default is
  8083), the same `STRUCTR_URL` for every check, and `down -v` on that project only when done.
  Ports: S1 8091, S2 8092, S4 8094. This computer has 24 GB; the owner's stack (3.5 GB) and two
  throwaways fit, so **at most two sessions hold a stack at a time**. `owner_stack.sh build`,
  `backup.py` and `tools/spikes/run_spikes.sh` refuse while another stack runs: no session runs them.
- No objective, weight or search change (`docs/optimizer-design.md` §4.5), no schema change and no
  scope reversal (`docs/CLAUDE.md`): a session that finds it needs one stops and records it in
  `todo.md` under "Offered, waiting on the owner".
- Owner data is never touched. A session that wants to try something on real data says so in its report.

## The sessions

| | Session | `todo.md` items | Files it owns | Stack | Can start |
|---|---|---|---|---|---|
| S1 | **Pantry bookings: who, rounding, substitutes** (built 2026-11-04, branch `claude/hungry-carson-b213a1`: who and rounding built; substitutes need a schema change, recorded in `todo.md`) | "A booking records who made it"; "A Use of the amount shown is not refused when it was rounded up"; "a cook recording which substitute it used" (`via_substitution`, invariant 18) | `mealplanner/pantry.py`, `pages/pantry.js`, `pages/lib/30_stock.js`, `40_bookings.js`, `50_pantry.js`, `methods/bookPantry.js`, `tools/check_bookings.py`, `tools/pantry.py`, `tests/test_pantry.py` | yes | now |
| S2 | **Checks independent of other data** | "`check_households.py` sweeps the grants and pantry operations an interrupted run made"; "`scripts/26a` independent of the instance's other recipes" | `tools/check_households.py`, `scripts/26a_planner_demo.py`, `tools/expected_state.json` if the demo's output changes | yes | **Done 2026-11-04** (branch `claude/jovial-jepsen-1020c1`): both items built (`todo.md`); what 26a's demo shows now is the owner's to approve in review |
| S3 | **Grocy import, first stage** | "Imports from similar applications, Grocy first" | new `tools/import_grocy.py`, new `mealplanner/grocy.py`, new tests and fixtures, a new `docs/imports.md`; calls `pantry.py`'s booking functions without changing them | no: offline against a recorded Grocy export (Grocy's public demo); a live run waits for S1 to merge | **first stage built 2026-11-04** (`docs/imports.md`), offline, over a hand-written export in Grocy's shape (the demo could not be reached); next: record the demo, and the live run after S1 |
| S4 | **Grocery tick books a purchase** | "Ticking a grocery item books a purchase" | `pages/shopping.js`, `pages/lib/90_shopping.js`, `methods/shoppingList.js`; books through `pages/lib/40_bookings.js`, which S1 changes | yes | after S1 merges: it books through S1's code |
| S5 | **A review sheet of Claude's judgment calls** | "A review of the FoodKeeper and retention matches"; "The first capabilities, reviewed"; the open review of the vocabulary added 2026-10-31 | writes only a report (an artifact or `docs/review-sheet.md`); reads `data/vocabulary.toml`, `data/foodkeeper/`, `data/fdc/` | no | now |
| S6 | **Weeks to judge the objective by** | "Weeks to judge the objective by" (third review #2) | new fixtures under `tests/fixtures/weeks/`, a report of each plan for the owner's verdict; runs `tools/plan_problem.py`, changes nothing in `mealplanner/planning/` | no | now |

S1, S2 and S3 together are the first wave (two stacks, S3 offline); S5 and S6 are read-mostly and can run
beside them. S4 follows S1. Each brief is the row above plus the rules: what done looks like is the
`todo.md` item built, its checks broken on purpose once to see them fail, and the item marked done.

**Also found 2026-11-04:** `origin/claude/laughing-maxwell-8yaern`, a cloud session's branch of
2026-09-26, 8 commits never merged (`tools/tunnel.sh` for Cloudflare Tunnel, two public pages, escaping
recipe names on the public recipes page). It predates two months of main. Whether anything in it is
still wanted, chiefly the escaping, is the owner's call before any session ports it.

## Not for a session yet: each waits on the owner

| Item (`todo.md`) | The decision it waits on |
|---|---|
| Usable measurements; what ingredients are sold in | "not to be built yet" (2026-10-31); the rounding of a weight is open |
| Releasing it for self-hosting; one backend for the pages; bookings from the terminal under the pages' lock | `docs/architecture-decision.md` |
| Batches 5 and 6 of the Structr features | the architecture decision (Batch 5); whether to build Batch 6, and which form |
| Weights as shares of the score; waste and cost in the objective | objective changes |
| A printed best-before date; thawing restarts the clock; storage and opening as a history; a cook's leftovers as stock; a pantry journal and undo | schema changes or scope reversals |
| The cheap security fixes | whether other devices should reach Structr (the port binding); the session-tied token would overlap S1 and S4 |
| A "Plan the week" button and preferences page; sharing through a service; a count or meal for a requested recipe; leftovers eaten instead | not yet asked for beyond the offer |
| Hard rule 2's wording; refusing a delete that breaks a rule | the owner's own to-dos |
