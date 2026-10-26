# Future work

**Status: a list, kept by Claude for the owner** (started 2026-10-26, when the owner asked for one).
Nothing here is started. Each item says where it came from. The owner decides what is next.

## Asked for

| Item | Asked | What it would take |
|---|---|---|
| **Imports from similar applications, Grocy first** | 2026-10-26 | Grocy's REST API or export: products as foods (matched to `data/vocabulary.toml`, or a new food to add), quantity units and their conversions as weights per item and densities, locations as storage conditions, stock entries as Purchase bookings (`mealplanner/pantry.py`), with their best-before dates once a printed date can be recorded (below), the shopping list, price history as `PriceObservation`s (J27, not built), and recipes as recipe files under `docs/recipe-copyright.md`. Then Mealie, Tandoor, Paprika and KitchenOwl exports, and schema.org `Recipe` data, the same way |
| **Releasing it for self-hosting** | 2026-10-24 | `docs/self-hosting.md`: written, not started, at the owner's word |

## Offered, waiting on the owner

| Item | Offered | What it would take |
|---|---|---|
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

## For the owner to do

- Sign in as Elijah and press one booking button: page bookings for a signed-in household member are
  untested (`docs/pages.md`).
- Copy `~/mealplanner-backups` off this machine now and then (`docs/backups.md`).
