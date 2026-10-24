# The pantry: booking stock in and out

The owner asked (2026-10-23) for pantry methods "for adding, subtracting, inventory, etc. similar to
Grocy", with Buy, Use / cook, Stock take, and Open / freeze / discard, on pages signed-in users can
write through. This records what was built, how each action maps onto the model, and what does not
fit yet.

## Grocy, for comparison

Grocy ([grocy.info](https://grocy.info), its REST API in `grocy.openapi.json`) keeps **stock entries**
(an amount, a due date, a purchase date, a price, a location, opened or not) and books every change
as a **transaction** in a journal that can be undone: *purchase*, *consume* (optionally *spoiled*,
from a chosen entry, by default opened first, then the soonest due, then the oldest), *open*,
*transfer* between locations, and *inventory*, which sets a new amount and books the difference as a
correction. Each product has default due days, and days after opening, freezing and thawing; a
minimum stock amount puts it on the shopping list; recipes consume their ingredients in one action.

## What each action writes here

None of it needs a new structural type or a stored figure. The actions write the shapes the model
already uses for what happens to food (data-model.md §4.1.1, §5, §5.5), so the inventory engine
(`mealplanner/inventory.py`), the shopping list, the planner's stock and the pages count it as they
count everything else.

| Action | Grocy | Written | Read back as |
|---|---|---|---|
| **Buy** | purchase | a `Process` of kind *Purchase* at a `TemporalRegion`; a `PortionOfSubstance` that `beginsToExistDuring` it, `locatedIn` a `ContainerObject` with its storage condition and *Sealed*; its Mass `Quality`, with an `observed` `Measurement` of the amount bought; its Perishability Class, if one is chosen or an earlier portion of the food had one | stock from that moment; expiry from the purchase (§5.5) |
| **Use** | consume | a `Process` of kind *Use* with an input `Allocation` about the portion, its amount an `observed` `Measurement` | current magnitude less the amount, from then on (§4.1.1) |
| **Count** | inventory | a new `observed` `Measurement` of the portion's mass | the new baseline: a recount is not a revision (§4.1.1) |
| **Open** | open | the container's opened status set to *Opened* (a container made for a portion in none, kept in the fridge and sealed, which is what one in none is taken to be) | the *Opened* shelf life |
| **Freeze** / **Move** | transfer | the container's storage condition set | that condition's shelf life |
| **Discard** | consume, spoiled | a `Process` of kind *Discarding* drawing everything left | on hand none; what was thrown away stays on record (§9's waste feedback) |
| **Mark cooked** (week page) | consume a recipe | a `Process` that `concretizes` the entry's Plan, drawing each ingredient the recipe buys (`nutrition_scope.raw_inputs`), scaled from its yield to the servings planned, from eligible stock of the food or a food below it, soonest to expire first; then the entry is `fulfilledBy` it | the shopping list and the reservations stop counting the meal |

The Process kinds are DomainTypes in a *Pantry Operation* hierarchy, made the first time one is used.
A cook has no kind: it `concretizes` its recipe, as data-model.md §10's braise does.

**Every booking is named by a token** (a page form carries one made when the page was drawn; the tool
makes one per run, or takes `--token`), and every node it writes is found by name before it is
created, so a form sent twice, or a page reloaded, writes nothing new (CLAUDE.md hard rule 5). A use
of more than a portion holds is refused (invariant 15); so is an amount that does not convert to
grams.

Where it is built: `mealplanner/pantry.py` (the bookings; `tests/test_pantry.py`),
`tools/pantry.py` (the same from the terminal), and `pages/pantry.js`, `pages/week.js` and the
bookings section of `pages/common.js` (the same from the pages, which follow the Python function by
function, as the pages' reads do). The pages write as the superuser, through Structr's
`$.doPrivileged`, as the tools do, and every node states its visibility (hard rule 4).

## What does not fit yet

These are findings, recorded rather than worked around (CLAUDE.md, "When something doesn't fit").

1. **Thawing has nowhere to go.** Storage condition is a static tag (CLAUDE.md, out of scope), so a
   portion's shelf life is read as if it had always been kept where it is now. Freezing is
   therefore roughly right (a few days in the fridge first are counted as frozen), but moving a
   portion back to the fridge dates its fridge shelf life from the purchase, so food frozen for a
   month shows as expired the moment it thaws. Grocy restarts the clock on thawing. Here that would
   be a thawing Process from which a new portion begins to exist, as a portion divided off a larger
   one does (`inventory.origin_time`'s known limit); that is modeling thawing as a transformation,
   which §13 declined, so it is the owner's call.
2. **Opening does not restart the clock either.** The *Opened* shelf life also runs from the
   purchase: milk bought a week ago and opened today expires as if opened a week ago. That is
   conservative, and it is what `inventory.instance_expiration` already did.
3. **A printed best-before date cannot be recorded.** Invariant 2 lets a `Measurement` be about a
   Quality *or a Disposition* (the shelf-life Disposition every food object bears, §5), but the
   built schema's `isAboutQuality` reaches Qualities only. So expiry comes from a Perishability
   Class's defaults or not at all. Recording the date would need that relationship to reach
   `Disposition`, a schema change.
4. ~~**Most foods have no Perishability Class, so most expiries are unknown.**~~ Answered by
   FoodKeeper (2026-10-24, data-model.md J31): each food now carries USDA FoodKeeper's shelf lives,
   which come before a class's; a class serves a food FoodKeeper gives no time for. Nine foods
   FoodKeeper sends to the package's printed date still have none (point 3).
5. **A cook's leftovers are not stock.** Recipes store no output mass (J28), so a cook writes no
   leftover portion; leftovers stay where the planner keeps them, as leftover entries of the week.
6. **Not built yet:** undoing a booking (Grocy's journal), a journal on the page, prices paid
   (`PriceObservation` exists in the schema but nothing writes one: J27), minimum stock on the page
   (StockPolicy target levels are applied by `tools/shopping_list.py` only), and products counted by
   barcode.

An Allocation's amount is an `observed` Measurement about no Quality, as in data-model.md §10 and
`scripts/15e`: about the portion's mass Quality it would be read as a new weighing. Invariant 2
says every Measurement is about one Quality; the draws have never met it.
