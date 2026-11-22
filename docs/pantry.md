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

**A booking names who made it** (2026-11-04): each Process it writes (a purchase, a use, a discard, a
cook) is `wasAssociatedWith` the Person who booked it (PROV; data-model.md K1). On the pages and in the
methods that is whoever is signed in, `$.me`, when they are a `Person` (taken before a page's booking runs
as the superuser); `mealplanner/pantry.py` takes it as `by`, which `tools/pantry.py` fills from `--by NAME`
or else the Person it signs in as (the tools' own account is none, so a booking from the terminal then
names no one). A stock take, an opening and a move write no Process, so they name no one yet: a stock
take as a Process of its own, with the weighing it generated, is part of the checks of
`docs/verification-and-sharing.md` §3.1. A booking sent again by someone else is still the first one's.

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

**An item is used up below 0.5 g** (`pantry.USED_UP_G`), what shows as 0 g, and leaves the page and the
tool's list. An amount is stored as it was given, so a Use typed as the rounded figure shown (996 g of
32 fl oz, which is 996.0005 g) leaves a crumb, which used to stay there for good with its expiry.

**A Use within half a gram of what a portion holds is all of it** (2026-11-04), either way: the page and
the tool show whole grams, so 996.6 g shows as "997 g", and a Use of 997 g, which invariant 15 used to
refuse as more than there is, now draws the 996.6 g; a Use of 996 g of 996.4 g draws the 996.4 g rather
than leave a crumb. Half a gram left (100 g of 100.5 g) is still left, as it still shows. More than half a
gram over is refused, and so is a Use of what is used up. The same rule is in `pantry.use` and the pages'
`PANTRY_ACTIONS.use` (`pages/lib/50_pantry.js`), and `tools/check_bookings.py` books one both ways.

## Products and barcodes

The owner asked (2026-11-13) for barcode scanning to stock the pantry, as Grocy has, with scanning
optional: "A user should be able to set the specific brand/barcode if they want or default use a
generic version." This is its first step, the data: what a barcode means here. Nothing scans yet
(`docs/todo.md`, "Barcode scanning for the pantry").

**A product is a packaged food**, written with what the schema has had since `scripts/29a`, so no
instance needs a migration (data-model.md §3, §6, §10: "a GTIN denotes a packaged-offering Type";
J38):

| What | Written as |
|---|---|
| the product ("Brand X chickpeas 400 g") | a `DomainType` in the Food Identity hierarchy, directly below the food it is a kind of |
| each of its barcodes | an `Identifier` in the scheme *GTIN* that `denotesType` it, its value the GTIN as 14 digits |
| what one package holds | a `DefaultSpecification` of kind *PurchaseQuantity* on it (§8) |

Sitting below its food, a product is that food to everything that already walks the hierarchy: a
portion of it counts as stock of the food (the pantry, the shopping list, a cook's draws, the planner),
and it takes the food's density, weight per item, shelf life and price, having none of its own. A
recipe goes on naming the food, never a product: nutrition reads a food's own figures and does not
look above it, so a product has none. A product is optional. The food itself is bought as before, and the pantry page's Buy offers both: it
used to offer every food nothing sits under (a food others sit under is a group, "Eggs" or "Poultry"),
and now offers every food nothing but products sits under, and each product
(`products.buyable`; `tools/check_pages.py` compares the page with it).

**What marks a Type as a product is that a GTIN denotes it**, so a product needs at least one barcode.
A brand with no barcode (a butcher's sausages) is bought as its food for now.

**A barcode is read as a GTIN** whatever length is printed (`products.normalize`): a UPC-A (12
digits), an EAN-13, a GTIN-14, an EAN-8, and the short UPC-E on small packages (8 digits starting 0
or 1), which is spelled out to its UPC-A. So the same package scans to the same product from any
scanner. A wrong check digit is refused as misread. So is a number a shop gives its own packs (a UPC-A
starting 2 or 4): it is no product's, and on meat, cheese or produce weighed in the shop it holds
that pack's weight or price.

Products come from a file. Which products a household buys is its own data, so the owner's is
`private/products.toml`, which git ignores:

```toml
[[product]]
name = "Brand X chickpeas 400 g"      # how it is named in the pantry
food = "Chickpeas (canned)"           # the food it is a kind of
barcodes = ["0 36000 29145 2"]        # one or more; spaces and hyphens are ignored
amount = 400                          # what one package holds
unit = "g"
```

```bash
python3 tools/import_products.py private/products.toml --check   # read the file; write nothing
python3 tools/import_products.py private/products.toml           # load; idempotent
python3 tools/import_products.py --find "0 36000 29145 2"        # the product a barcode names
python3 tools/pantry.py scan 036000291452 2 --storage Pantry     # buy two packages of it
```

Loading refuses, before writing anything, a food the instance does not have, a group of foods, a
product below a product, a name that is already a food, a barcode that belongs to a product the file
does not name, and a package size that does not convert to grams (twelve of a food with no weight per
item). A barcode a product no longer lists is removed; a product the file no longer names is left,
since stock may be of it. `scan` books a Purchase of the product, so many packages of what one holds,
through `pantry.buy`.

Tried on a throwaway instance holding the whole vocabulary (2026-11-13): two products loaded, and
again with nothing written; two dozen eggs scanned were 1,200 g of Egg on hand, with Egg's shelf life;
`check_pages.py` found Buy offering the 297 foods and products `products.buyable` gives, and, with the
page's old rule put back on purpose, named the two foods it then dropped; `check_bookings.py` found the
pages' bookings unchanged.

What this step leaves, each in `docs/todo.md`: a scan box on the pantry page and a phone's camera; an
unknown barcode looked up (Open Food Facts) and matched to a food by the user; a product's own label
nutrition (FDC's branded foods carry the same GTINs); where a product is kept by default (a scan
books to the fridge unless `--storage` says otherwise, as Buy does); a product added from the page
rather than a file; and a shop's own weighed packs.

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
   (StockPolicy target levels are applied by `tools/shopping_list.py` only), and scanning: a product
   and its barcodes can be recorded and bought by barcode from the terminal ("Products and barcodes",
   above), but no page scans one yet.

An Allocation's amount is an `observed` Measurement about no Quality, as in data-model.md §10 and
`scripts/15e`: about the portion's mass Quality it would be read as a new weighing. Invariant 2
says every Measurement is about one Quality; the draws have never met it.
