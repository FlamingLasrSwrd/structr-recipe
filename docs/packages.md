# Packages: what foods are sold in, and what a shopping list leaves over

What each food is sold in, and a shopping list that buys whole packages and says what will be left
(data-model.md J39). Asked for by the owner on 2026-10-31 ("This application needs to be aware of the
amount that ingredients are sold in. Buying a whole rotisserie chicken is cheap but needs to be used
that week, which affects wastage"), and to be built on 2026-11-22. This is stages 1 and 2 of the four
in `docs/todo.md`, and stage 3, the form a food is bought in (2026-11-23, "The form bought" below);
stage 4 is under "Not built".

## What a food is sold in

A package size is a `DefaultSpecification` of kind `PurchaseQuantity`, the Default Kind the seed
vocabulary has named since `scripts/05` (data-model.md §8) and nothing used until now, keyed by a food
Type, on a Type in the `Package Reference` hierarchy. It is how prices are layered (`docs/prices.md`),
and needs no schema change: the hierarchy, its levels and the defaults are data.

```
US supermarket          data/packages.toml: common U.S. supermarket sizes, all estimated
  Home packages         the owner's own (private/packages.toml)
```

Its value is a `QuantitySpecification` in the unit the package is sold in (14.5 oz, 32 fl_oz, 12 each),
converted to grams where it is read, with the food's density or weight per item from the vocabulary.
A food may be sold in up to four sizes (a 14.5 oz and a 28 oz can of tomatoes); each is its own
default, named `<level> -- <food> -- <label>`, the label being what the list shows ("28 oz can",
"dozen", "bunch (about 6)").

Resolution: the nearest level that gives a food any size gives all of its sizes, so the owner's level
naming a food replaces that food's public sizes rather than adding to them. A food no level names
takes its nearest ancestor food's sizes (Butter (salted) takes Butter's), as a price does. Several
defaults of one kind with one key on one Type are what `defaults.resolve_all` refuses as ambiguous,
which is why sizes are resolved by `packages.package_table`, not by `resolve_all`.

**The public sizes are counted from labels where they can be, and estimated where they cannot.**
`data/packages.toml` holds 166 foods, each with an estimate written down from general knowledge of U.S.
supermarket shelves (2026-11-22). The owner then asked for a real source. USDA FoodData Central's
Branded Foods dataset (public domain) records the net weight printed on each product's package
(`package_weight`, "15 oz/425 g") for about 875,000 of its 2.0 million records; no other open dataset
was found that does. (Open Food Facts has a crowd-sourced quantity field, under the share-alike ODbL,
which would bind a pinned extract; its site could not be reached from the session that built this, so
it was not compared.) So 133 foods carry a rule, `[package.fdc]`, that picks their products out of
it, and `tools/package_extract.py` counts the sizes those products come in and pins the count in
`data/packages/fdc.json`, as `data/prices/` pins prices. 114 foods have a count that stands; their
sizes are loaded `sourced`, each with its share in `source`:

```
FoodData Central Branded Foods (2026-10-29): 265 of 455 U.S. products (58%), from 82 of 110 brand owners,
come in this size; public domain: 14.5 oz = 411.068 g
```

The other 52 keep their estimate, loaded `estimated` and marked on the shopping list: 33 have no rule
(sold by count, loose or by the bunch, or not in the dataset, such as wine), and 19 matched too few
products (spices, most often, whose jars differ by brand; coconut milk does stand, with 27).

How a count is made (`mealplanner/fdc_packages.py`; each threshold a proposal for the owner to retune):

- **Which products.** A rule is three regular expressions, case ignored: `category` on the record's
  `branded_food_category`, `match` and `exclude` on its description. The exclusions carry most of the
  work: flavours, mixes, prepared dishes, snack packs, reduced-fat versions, other foods named alongside.
  One record per product (GTIN), its latest; U.S. market; not discontinued; not sold to food service
  only.
- **What size.** As the label prints it in ounces, to the nearest quarter ounce: U.S. labels are designed
  in ounces and pounds, and the metric figure beside them is a rounded conversion. Weight and fluid
  ounces count together (a carton of broth is "32 oz" on one record and "32 fl oz" on the next). A size
  within 1.5% of a more common one is that size ("1.81 kg" is the 4 lb bag; a 15.25 oz can is not a
  15 oz one).
- **Which sizes are common.** At least 10% of the food's products, from at least 5 brand owners; at most
  four, the most common first. A food needs 20 products from 5 owners in all, or its estimate stands.
- **How it is written.** In the kind of unit the estimate uses (fl_oz for a food sold by volume; oz,
  or lb for whole pounds from 2 lb). A counted size within 2% of an estimated one is that size, with its
  figure and label ("500 mL bottle", 16.9 fl oz, where the count says 17).

A count is of products on the market, not of sales: a store brand's can counts once, as a national
brand's does. That says what a shopper commonly finds, which is what the list needs. What the count
changed, against the estimates: soy sauce is commonly 10 fl oz (the estimate said 15), honey 16 oz before
12, sour cream 16 oz before 8, frozen peas and corn 16 oz before 12, Dijon 12 oz before 8; and it added
sizes the estimates lacked (a quart of milk, 10 lb of flour and sugar, a 28 oz jar of peanut butter).

Left out on purpose: what is sold loose or cut to order (most fresh produce, meat and fish from a
counter), what is bought in one form and used in another (stage 3), what a recipe makes, and tap water.

```bash
python3 tools/package_extract.py --fetch 2026-10-29 # download a release of the FDC branded CSV zip (~450 MB, once)
python3 tools/package_extract.py --report           # count again after changing a rule: re-pins data/packages/fdc.json
python3 tools/import_packages.py --check            # the file and the pin against data/vocabulary.toml; writes nothing
python3 tools/import_packages.py                    # the public level (after import_vocabulary.py); idempotent
python3 tools/instantiate_profile.py packages private/packages.toml        # the owner's level
python3 tools/instantiate_profile.py packages --show "Home packages"       # every size, as the owner sees it
```

`--check` refuses, offline, a food the vocabulary does not have, a size by volume or count for a food
with no density or weight per item, and a rule the pin was not counted with (run `package_extract.py`
again); a test runs the same checks on the shipped files. Counting reads the 1.3 GB of CSV straight from
the zip, keeps only the products in a rule's category, and takes about a minute and 320 MB of memory. Loading refuses
the same against the instance. A size the file no longer names is removed.

## The owner's own sizes

```toml
# private/packages.toml
name = "Home packages"
profile = "US supermarket"                   # what to fall back on
[own]
"Olive oil" = { sizes = [[1, "l", "1 L tin"]], note = "Costco" }
"Egg" = { sizes = [[24, "each", "two dozen"]] }
```

An owner's size is `specified` and `sourced`, and names the file. Taking a food out of the file
removes its sizes, and it falls back to the public ones. A food the public level packages but the
owner buys loose (a bulk bin) cannot yet be said to be loose; give it the size it is weighed out in.

## The shopping list, rounded up

`tools/shopping_list.py`, the shopping page and the `shoppingList` method read a package level: the
week file's `packages = "<level>"` for the tool and `?packages=<level>` for the page, by default "Home
packages" where the owner has one, else "US supermarket", else none (and the list says amounts are what
the recipes use, as before). For each food to buy:

- **What to buy** is the whole packages that leave least over (under a milligram short is not short),
  then the fewest packages, then the fewest of the sizes listed first (in the order of their names:
  the graph keeps no file order) (`packages.choose`): 850 g of tomatoes from 14.5 oz (411 g) and
  28 oz (794 g) cans is one of each (355 g left), not three small ones (383 g left) or two large. A food the recipes count (eggs, tortillas)
  that no level packages is bought in whole items; anything else, as much as is needed.
- **What is left over** is what is bought less what the list needed (what the week's meals use beyond
  stock on hand, and a stock policy's level where `tools/shopping_list.py` applies one).
- **Until when it keeps**: what is left is taken to be in a package opened at the food's first use this
  week. It keeps as long as the longest FoodKeeper figure for it opened, of the fridge's and the
  pantry's (J31); a food with no opened figure keeps as it does unopened where the pantry assumes it is
  kept. So an opened can of beans keeps days in the fridge, not its unopened years in the pantry. Both
  count from the first use, as if bought that day, which a list grouped by the day each food is first
  needed allows: bought earlier, it keeps less long (an avocado bought on Sunday for Wednesday may not
  last). A whole package left unopened keeps longer than the date shown.
- **The cost** is of what is bought, whole packages included, with what is left over priced apart and
  totalled. Before this the cost was of what the recipes used, which understated a week's shopping.

From a throwaway instance holding the vocabulary and the 20 public recipes (2026-11-22), a week of
five cooks:

```
First needed Mon 23 Nov:
  Carrot                        1 x 1 lb bag (about 454 g)+    $1.84   Moroccan Chicken Stew with Couscous v1
                                390 g (0.9 lb) left over ($1.58); keeps to Mon 07 Dec 2026 unopened
  Chicken broth                 1 x can (14.5 oz) (about 411 g)+    $0.84   Moroccan Chicken Stew with Couscous v1
                                38 g (1.3 oz) left over ($0.08); keeps to Thu 26 Nov 2026 once opened
...
About $55.40 at 'Home prices', of which $42.07 is left over (* priced from an estimate); not priced: ...
```

Most of that $42 is bottles and jars bought for a spoonful (a litre of olive oil, fish sauce, sesame
oil), which last for months; the perishable part is what stage 4 would weigh.

The page computes the same in Structr's JavaScript (`pages/lib/90_shopping.js`: `packageTable`,
`choosePackages`, `leftOverKeeps`, `roundUp`), and `tools/check_pages.py` compares, for every food,
the packages, what is bought and left, its cost and the date it keeps to with Python's.

Tried on that instance: the public sizes loaded (376 nodes) and loaded again with nothing written; the
owner's level replaced one food's size; `tools/check_pages.py` found the page and `shoppingList` agreeing
with Python on all 41 foods to buy, and, with the page's opened-shelf-life test taken out on purpose,
34 differences. It also found a gap of its own, fixed: a food a stock policy tops up was left out of the
foods to buy but not out of what the pantry covers, where the page, applying no policy, lists it.

## The form bought

Stage 3 (data-model.md J41, `mealplanner/yields.py`): a recipe weighs the part of a food it uses, and a
shop sells something else. Two kinds, both the `Yield` default the model has named since §5.1, so no
schema change:

- **A trim**: an onion is sold with its skin. A recipe's 270 g of onion, and FDC's figures per 100 g,
  are of the edible part; bought by weight, that is 270 / 0.90 = 300 g of onion. A trim is a Yield on
  the food, keyed by the method `Trimming`, whose target is the food itself. A count of items needs
  no trim (FDC's "1 medium onion", 110 g, is of the edible part), so a food bought whole by count is
  bought as before.
- **A yield from another food**: lemon juice is sold inside lemons. A Yield on Lemon, keyed by
  `Juicing`, whose target is Lemon juice: a gram of lemon gives 48 / 58 = 0.83 g of juice (FDC's
  "lemon yields" 48 g, over a lemon's 58 g). Egg whites come from eggs the same way (`Separating`).

```toml
[[food]]
name = "Yellow Onion"
trim = { refuse = 10, what = "skin and ends", source = "..." }

[[food]]
name = "Lemon juice"
yield_from = { food = "Lemon", method = "Juicing", portion = "lemon yields" }
```

What the shopping list does with them (the list in Python, the page and the `shoppingList` method alike):

- A food another yields, and that the package level sells in **no size of its own**, is bought as that
  food. What the pantry holds of it counts first (a bottle of lemon juice already open); what is left,
  over the yield, joins that food's line, against what the pantry holds of that food. The line says
  what it is for: `Lemon  2 (about 116 g)  for Lemon juice (50 g); salad`. A food a source yields is
  bought whole by count when the source has a weight per item (lemons, eggs). A food the package level
  does sell (data/packages.toml sells the drained beans in a can drained, so their own sizes stand) is
  bought as itself, so a household that buys bottled juice gives Lemon juice a size on its own level.
- A food with a trim is bought as it is sold: a package by weight or volume holds that fraction of
  its weight as a recipe weighs it (a 3 lb bag of onions holds 1,225 g of onion), and a need bought
  loose is shown as bought (`300 g (0.7 lb) as bought`, `90% of it as bought is used (less skin and
  ends)`). The grams a line buys, has left over and is priced by stay those a recipe weighs.

Where the figures come from. The yields from another food are worked out from two FDC portions,
`calculated`: lemon, lime and orange juice, egg whites. The trims, 22 fresh fruits and vegetables
whose loss is plain (not cauliflower, kale or tomatoes, whose figures were too unsure to state), are
USDA SR28's refuse: SR28's FOOD_DES file gives every SR food's refuse as a share of it as purchased.
That file's host was not reachable from the session that wrote them, so each is stated as an
estimate, Claude's recollection of SR28's figure, to be reviewed. Where SR28 can be downloaded (the
owner's computer):

```bash
python3 tools/yield_extract.py --fetch   # .cache/sr28/sr28asc.zip, then pins data/yields/sr28.json
STRUCTR_URL=http://localhost:8085 python3 tools/import_vocabulary.py
```

prints each estimate beside SR28's own and pins SR28's; the vocabulary then loads SR28's, `sourced`, and
a food SR28 gives no refuse loses its trim.

Not yet: the rotisserie chicken the owner named, which needs two foods the vocabulary lacks (the bird
and its meat, with FDC records to pin) and then one `yield_from`; one step of yield only; a price is
read per gram as a recipe weighs it, as Purchase to Plate's are, so an owner's price for a trimmed
food, stated per gram as bought, prices it about its refuse low; the pantry books a purchase as it is
weighed, so a bag of onions booked by weight counts its skins as stock; and the planner's weighing of
package waste (stage 4) does not read the purchased form.

## Not built

- **Stage 4, the planner weighing what is left over**: choosing recipes that share what a purchase
  leaves before it keeps no longer, and counting what they do not as waste. That changes the objective
  (optimizer-design.md §4.5), which is the owner's decision: proposed in `docs/todo.md`.
- **Products** (barcode scanning, step 1, `docs/pantry.md` "Products and barcodes"): a product carries
  its own PurchaseQuantity on its own Type, unkeyed, which `package_table` does not read: the list is by
  food. Once a household can choose a product for a food, the list could buy that product in its
  package.
- **Ticking an item books a purchase**: the amount it books would be the packages bought, not what the
  recipes use (`docs/todo.md`, "A grocery item checked off goes into the pantry").
