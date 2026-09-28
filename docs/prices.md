# Prices: interim public figures, the owner's own, and what things cost

Food prices until the owner's own prices and tracked purchases replace them (data-model.md §18
J27). Built 2026-09-28 at the owner's request: "Are there publicly available datasets for general
pricing information anywhere? At least until I can either manually edit the values or we actually
start tracking purchases."

## Where the figures come from

Two public sources, both U.S. government works, pinned in `data/prices/` so loading never needs
the internet (`tools/price_extract.py`, like `data/fdc/` for nutrition):

| Source | What it is | Strength | Weakness |
|---|---|---|---|
| **BLS Average Price Data** | the CPI's monthly average retail prices, U.S. city average and four regions | current (latest month), priced as bought, and the West region's where BLS publishes it | about 45 foods, 19 of which the vocabulary uses |
| **USDA ERS Purchase to Plate National Average Prices (PP-NAP)** | prices from retail scanner data for the foods people report eating (FNDDS food codes) | 4,435 foods | 2017-18 prices, national only, per 100 g of the food **as eaten**: cooked and edible part |

Purchase to Plate prices are brought to today's by the CPI for food at home (U.S. city average,
`CUUR0000SAF11`): the latest month over the mean of 2017-18, a factor of 1.34 in August 2026. As
eaten matters for a food bought raw and eaten cooked: the price of cooked shrimp, used for raw,
overstates a raw gram by about the weight lost in cooking, so such a price is marked `cooked` and
`estimated`. For a food bought as it is eaten (produce, cheese, oil, sauces) the two are the same.
Edible grams suit the recipes, which weigh what is used.

`data/prices.toml` maps each vocabulary food to its source, 133 of the 191 foods:

- **BLS** where BLS prices the same thing as bought (flour, eggs, milk, butter, chicken breast,
  sirloin, bacon, potatoes);
- **Purchase to Plate** for the rest (produce, cheese, oils, sauces, nuts, canned goods);
- `proxy = true` where the source prices a similar food (jasmine rice at the long-grain white rice
  price, balsamic at the vinegar price), with a note saying which way it errs;
- **unpriced** where nothing public fits: spices and dried herbs, salt, leaveners, panko, oats,
  tomato paste, and the meal kits' own sauces, pastes and stock concentrates. A cost names them
  instead of guessing.

Status follows J21: a BLS price is `sourced`; a Purchase to Plate price brought forward is
`calculated`; a proxy or a cooked price is `estimated`. Every price's `source` gives the series or
food code, the original figure and the conversion.

## How they are layered

A price is a `DefaultSpecification` of kind `Unit Price`, keyed by a food Type and valued in
dollars per 100 g (`USD_per_100g`), on a Type in the `Price Reference` hierarchy. It is the same
mechanism as the profiles (docs/profiles.md), resolved the same way: the nearest level with a price
wins.

```
US prices 2017-18 adjusted (Purchase to Plate)
  US prices (BLS)            overrides it where BLS has the food
    West prices (BLS)        overrides that where BLS publishes the West's price
      Home prices            the owner's own (private/prices.toml)
```

A food with no price at any level takes its parent food's (`Butter (salted)` → `Butter`).

## The owner's own prices

```toml
# private/prices.toml
name = "Home prices"
profile = "West prices (BLS)"              # what to fall back on
[own]
"Olive oil" = { price = 11.99, amount = 16.9, unit = "fl_oz", note = "Costco, 2026-09" }
"Egg" = { price = 3.49, amount = 12, unit = "each" }
```

```bash
python3 tools/import_prices.py                                   # the public levels
python3 tools/instantiate_profile.py prices private/prices.toml  # the owner's level
python3 tools/instantiate_profile.py prices --show "Home prices" # every price as the owner sees it
```

An owner's price is `specified` and `sourced`, converted to dollars per 100 g with the food's
density or weight per item, and names the file. Taking one out of the file removes it, and the
food falls back to the public price. Tracked purchases, which would suggest these rather than
need typing, are proposed in `verification-and-sharing.md`.

## What things cost

Computed, never stored (`mealplanner/prices.py`). A recipe's cost a serving is its raw,
non-optional ingredients in grams (the same ones nutrition counts) times their price, over its
servings. An ingredient with no price, or no weight to price, is left out and named, so the figure
is a floor on what the recipe costs, not a guess at the rest.

`tools/plan_week.py` reports the week's cost when the week file names a price level
(`prices = "Home prices"`): the meals it cooks (a cook costs the servings it makes, so leftovers
cost nothing more), a day's average, each recipe's cost a serving, and what was not priced or rests
on an estimate. Cost does not affect which meals are chosen: it is not in the objective
(optimizer-design §4.5), and putting it there is the owner's decision.

## Limits

- National and regional averages, not a store's shelf price. Brand, size and store matter more than
  region.
- A price is per 100 g of what a recipe uses, so buying a whole package for one recipe costs more
  than its cost says. Waste of that kind is the planner's waste term, not the price's.
- Purchase to Plate is from 2017-18: relative prices have moved since, and one CPI factor for all
  foods does not follow them (eggs and beef rose more than most).
