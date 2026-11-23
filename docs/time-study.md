# Time study: the overhead of making food, with and without the meal planner

**Status: an estimate, 2026-11-23**, asked for by the owner: "The goal of this project is to reduce the
overhead cost of making food. Let's do some realistic checks of the processes the project has so far."
Most figures here are estimates, and each is labelled:

- **measured**: timed on the owner's instance (read only, 2026-11-23: pages drawn, nothing booked) or recorded
  in this repository;
- **sourced**: a published figure, linked under "Sources";
- **model**: worked out by `tools/scan_curve.py` ("The barcode curve") from stated assumptions;
- **estimate**: Claude's judgment of how long a step takes, from walking through the pages' code. None of
  the app's steps was timed with a person holding a phone, and that is the first thing to check (the last
  section says how).

The households are placeholders (CLAUDE.md: no personal information); none is the owner's.

## The answer in short

| Weekly minutes, food overhead (cooking itself excluded) | A: one adult | B: two adults, one tracking nutrition | C: two adults, two children |
|---|---|---|---|
| Without the app | 120 | 250 | 260 |
| With the app, first month (most barcodes new) | 120 | 185 | 270 |
| With the app, steady state (about six months in) | 115 | 175 | 250 |
| With the app, steady state, after the first five changes at the end | 95 | 145 | 205 |

Cooking, prep and cleanup are another 275, 510 and 625 minutes a week in the three households, two to
three times the overhead.

- **What the app saves today** is planning (the planner replaces deciding the week) and, for a household
  that tracks nutrition, nearly all of the logging. Household B saves over an hour a week; A and C come out
  about even, because what they save in planning they spend again putting shopping into the pantry.
- **What the app adds** is booking food into and out of the pantry: every item bought is entered a
  second time, on the pantry page, and everything eaten off the plan has to be booked or recounted, or
  the stock and the shopping list drift. That is new work with no counterpart without the app: 10 to 55
  minutes a week depending on the household and how many barcodes are still new.
- **Where the most uncovered time is**: cooking and cleanup (the app touches it only through which recipes
  it picks), then the shopping trip itself (travel and the store: 60 to 140 minutes a week, untouched).
- **Barcode scanning**: about 15 seconds of app time per item for a product the instance knows, about 70
  for a new one, and about 25 for food with no barcode, bought by name. New products fall from all of
  them in week 1 to about a third by week 12 and a sixth by week 52, but never to none: brands, sizes and
  shops change. Steady state is 10 to 25 minutes of booking a week.
- **The biggest single saving available is not in the pantry**: the planner's `cooking_time` weight cut
  a two-person week's cooking from 610 to 465 minutes when it was measured (2026-10-24,
  `docs/optimizer-design.md` §12). It is off unless the week file sets it, and turning it on by default
  is an objective change and the owner's call.

## What counts, and the figures behind it

The overhead of making food is everything around the cooking: deciding what to eat, finding out what is
in the house, writing the list, the shopping trip, putting it away, keeping track of what is left, and
throwing out what spoiled. Cooking and cleanup are counted separately, because the app hardly touches
them.

| Figure | Value | Kind |
|---|---|---|
| Food preparation and cleanup, per person aged 15 and over, average day, US 2024 | 0.67 h (40 min): 0.53 h preparing, 0.13 h cleanup | sourced (ATUS table A-1) |
| Grocery shopping, same population | 0.11 h a day (7 min), averaged over everyone; 0.76 h (46 min) for those who shop that day | sourced (ATUS table A-1) |
| Time in the store, per trip | about 43 min in the US, 32 in Canada (2018 survey of 1,053 people) | sourced |
| Grocery trips | about 1.6 a week per person, 2.8 per household (FMI, 2026) | sourced |
| Deciding what to eat | 43 min a week (UK poll of 2,000 adults for a sauce brand: a weak source) | sourced, weak |
| Food a US household acquires and wastes | 31.9% on average; most households between 20% and 50% | sourced (Yu and Jaenicke, 2020) |
| Cooking time the planner saves with `cooking_time` set | 610 min a week at 0, 465 at 0.5 to 2, 415 at 4 (the owner's recipes, two people, a week of 2 Nov) | measured (`docs/optimizer-design.md` §12) |
| Page times on the owner's instance | in "Where the app's own processes cost most" | measured |

## The households

Three households, each with a weekly routine (all estimates of a typical routine, not anyone's):

- **A: one adult, working weekdays.** Cooks 4 dinners a week at 2 servings, the second for the next
  day's lunch; the same breakfast every day. One big shop a week and a top-up every other week: about
  20 lines on the list, 12 of them barcoded packages and 8 produce, meat or bulk food with no barcode.
- **B: two adults, one with nutrition targets** (protein and sodium, say, for a health reason). 5 dinners
  cooked and 2 nights of leftovers, lunches from leftovers, one dish made at a Sunday prep session. One
  big shop and one top-up a week: about 35 lines, 22 barcoded. Without the app the one with targets logs
  what they eat in a tracking app.
- **C: two adults, two school-age children.** 6 dinners cooked and one takeout, breakfasts every day,
  packed lunches for the children on school days. Two shops a week and a top-up every other week: about
  60 lines, 40 barcoded.

## Without the app

Weekly minutes per step. "Basis" says where each figure comes from.

| Step | A | B | C | Basis |
|---|---|---|---|---|
| 1. Decide the week's meals and find the recipes | 20 | 35 | 45 | estimate; the weak poll's 43 min of deciding is in this range |
| 2. Nutrition: log meals in a tracker | 0 | 70 | 0 | estimate: about 10 min a day for one person |
| 3. Check the fridge and cupboards, write the list | 10 | 15 | 20 | estimate |
| 4. Travel to the shop and back (20 min a trip) | 30 | 40 | 50 | estimate: 1.5, 2 and 2.5 trips a week |
| 5. In the store | 30 | 55 | 95 | sourced (about 40 min a big trip), smaller for A; 15 min a top-up |
| 6. Unload and put away (about 10 s an item) | 5 | 8 | 12 | estimate |
| 7. "What's for dinner?" again mid-week: plans that changed | 10 | 10 | 15 | estimate |
| 8. Leftovers: deciding what is still good and when to eat it | 5 | 5 | 10 | estimate |
| 9. Clearing out spoiled food | 10 | 10 | 15 | estimate |
| **Overhead** | **120** | **248** | **262** | |
| Cooking, prep and cleanup | 275 | 510 | 625 | estimate per meal, checked against ATUS's 40 min per person a day |

How the cooking figures were built: A, 4 cooks of 45 min, 7 breakfasts of 5 min and 4 cleanups of 15;
B, 5 cooks of 50 min, a 90 min prep session, 14 breakfasts of 5 min and 5 cleanups of 20; C, 6 cooks of
55 min, 7 breakfasts of 10 min, 10 packed lunches at 7.5 min each and 6 cleanups of 25. ATUS's 40 minutes
per person per day gives 280 for A and 560 for two adults, so these are ordinary households.

The hidden cost is step 9's cause: about a third of the food a household acquires is thrown away
(sourced), so about a third of steps 4 to 6 is spent buying, carrying and storing food that is never
eaten.

## With the app, as it is on 2026-11-23

What each step is today, from the pages, the methods and the tools (`docs/pages.md`, `docs/pantry.md`,
`tools/plan_week.py`):

| Step | What the user does now | Covered? |
|---|---|---|
| Decide the week | Ask for recipes from their pages (**Cook in the week of ...**), edit `private/week.toml` (the start date, what to cook), run `tools/plan_week.py` in a terminal on the computer that runs Structr (about 5 minutes of search: `total_time_s = 300`), read the report, run it with `--commit` | Yes, from a terminal only. Nobody without a terminal on that computer can plan a week |
| Nutrition | Nothing for planned meals: the nutrition page judges every target per person. A meal not eaten as planned is marked on the week page (**Didn't make it**, with what was eaten instead) | Yes, for planned meals. Snacks and food off the plan are not counted |
| Check the pantry, write the list | The shopping page: what to buy in whole packages, less what the pantry holds. Only as good as the pantry's figures | Yes. The list is ordered by the day each food is first needed, not by aisle, and its ticks stay in that browser |
| Travel and the store | As before | No |
| Put away | As before, and then every item is booked on the pantry page: a scan (camera, scanner or typed) or the food typed by name, the amount, where it is kept, **Add to pantry** | Yes, at a cost (below) |
| Recipes | The recipe page writes each step as a sentence; **Mark cooked** on the week page takes the ingredients out of the pantry | Yes. The cooking itself is not changed |
| Mid-week changes | **Didn't make it** or **Won't make it** on the week page; a meal freed that way is planned again from the terminal | Partly |
| Leftovers | Planned into later meals by the planner. A cook's leftovers are not stock (`docs/pantry.md` finding 5) | Planned, not tracked |
| Food eaten off the plan | Booked on the pantry page as **Use** (in grams), or put right later with **Count** (in grams) | Yes, at a cost; new work |
| Spoiled food | The pantry lists what expires soonest first (FoodKeeper's shelf lives); **Discard** books it | Yes |
| New recipes | A recipe file in `private/recipes/`, transcribed by hand or by Claude, every food already in the vocabulary, then `tools/import_recipe.py` in a terminal; a food the vocabulary lacks needs `data/vocabulary.toml`, its FDC match and `tools/import_vocabulary.py` | Yes, in a terminal |
| Keeping it running | Structr has to be up for the pages to answer: `tools/owner_stack.sh up` after each restart of that computer (about a minute, and a slow first page) | New work |

### Weekly minutes, steady state

Steady state means about six months in, with most barcodes known (the curve below). The booking times
are per item, from "Barcode scanning" below.

| Step | A | B | C | What changed |
|---|---|---|---|---|
| 1. Decide the week | 10 | 12 | 15 | the planner decides; a person edits the file, waits, reads and commits (estimate) |
| 2. Nutrition | 0 | 10 | 0 | only what was not eaten as planned is marked (estimate) |
| 3. Check, list | 3 | 5 | 7 | the list is made; a glance at what the pantry claims is there |
| 4. Travel | 30 | 35 | 45 | fewer forgotten things, so a quarter of a top-up trip less for B and C (estimate) |
| 5. In the store | 30 | 55 | 95 | as before: the list is not in aisle order, which costs a little and whole packages save a little |
| 6. Put away and book | 14 | 23 | 36 | put away as before (5, 8, 12), plus booking: A 9, B 15, C 24 (below) |
| 7. Mid-week changes | 5 | 5 | 10 | a minute on the week page each; planning a freed meal again needs the terminal |
| 8. Leftovers | 2 | 2 | 5 | planned |
| 9. Spoiled food | 5 | 5 | 8 | the expiry list catches it sooner |
| 10. Food eaten off the plan (new) | 5 | 8 | 15 | a Use at about 25 s each (5, 8, 20 a week), a few Discards, a monthly recount of what drifted |
| 11. Mark cooked (new) | 1 | 1 | 2 | about 10 s a cook |
| 12. New recipes, spread over the weeks (new) | 5 | 10 | 10 | half a new recipe a week for A, one for B and C, about 10 min of attention each with Claude transcribing |
| 13. Keeping it running (new) | 2 | 2 | 2 | a restart now and then |
| **Overhead** | **112** | **173** | **250** | without the app: 120, 248, 262 |

### The first month, and setting up

In the first weeks almost every barcode is new, so step 6 is much larger: in week 1, booking takes about
17 minutes for A, 31 for B and 55 for C (every barcode new, at 70 s each, plus the food bought by name),
falling by half in about two months. The first month averages about 120, 185 and 270 minutes of
overhead: even with living without the app for A, a little worse for C, and still ahead for B.

Setting up is once, and large (estimates):

| One-time step | Time |
|---|---|
| The stack, the household and targets file, the kitchen profile | an evening for someone at home in a terminal; out of reach for anyone who is not |
| Booking what is already in the house (about 150 items: half barcoded and new at 70 s, half by name at 25 s, opened packages weighed) | 2 to 3 hours |
| Recipes beyond the 20 that ship with it (`data/recipes/`) | 10 to 40 min each: 20 own recipes is 3 to 13 hours |

## Barcode scanning: time per item

Per item, the time the pantry page adds beyond putting the item away, on a phone over HTTPS
(`docs/pantry.md`). Each booking is a form sent to the page, and the whole pantry page is drawn again
after it, so every step that sends a form waits for one page load (measured on the owner's instance: 1.4 s to draw, plus the phone's network and drawing, about 2 s in all).

| Item | Steps | Time | Kind |
|---|---|---|---|
| **A product the instance knows** | tap **Scan with camera** (the camera stops when the page reloads, so once per item); aim until it reads twice; page load with Buy filled in; change where it is kept if not the fridge (the default; about half of items); type the grams for more than one package (there is no "×2"); **Add to pantry**; page load | **about 15 s** (12 to 20) | estimate |
| A known product with a USB or Bluetooth scanner | the scanner types the barcode and Enter; the rest as above | about 10 s | estimate |
| **A new product, found on Open Food Facts** | as above, then **Add a product** opens: Open Food Facts fills in the name and size (up to 10 s, usually 1 to 3); check them; type the food it is a kind of and choose it from a list of 499 foods, which means knowing the vocabulary's name for it ("Chickpeas (canned)"); **Add product**; page load; then the known product's steps | **about 70 s** (50 to 90) | estimate |
| A new product Open Food Facts does not know | as above, typing the name and finding the size on the package | 75 to 100 s | estimate |
| A new product whose food is not in the vocabulary | cannot be finished on the page: bought as the nearest food, or left; adding the food is a terminal job (`data/vocabulary.toml`, its FDC match, `tools/import_vocabulary.py`) | minutes now, and tens of minutes later | estimate |
| Food with no barcode (produce, the butcher's) or a shop's weighed pack (its barcode holds a price, and is refused as no product's) | type the food and choose it, the amount (weigh it or read the label), where it is kept, **Add to pantry**, page load | about 25 s | estimate |
| For comparison: putting the item away | | 5 to 10 s | estimate |

A best-before date is never typed (expiry comes from FoodKeeper's shelf lives), which keeps booking
faster than in Grocy, where a due date is asked for.

## The barcode curve

How many of a week's barcoded lines are new products, by week, from `tools/scan_curve.py` (model; about 20 s to run). Its
assumptions: each household buys from a pool of 400 products with Zipf popularity (a few bought nearly
every week, a long tail bought rarely), and 1% of the pool is replaced each week by another product at the
same popularity: a new size (a package of another size is another product, `docs/pantry.md`), a brand
on sale, another shop, a season. Booking time is the barcoded lines at 15 s each when known and 70 s when
new; food with no barcode (A 8, B 13, C 20 lines a week at 25 s) adds a steady 3, 5 and 8 minutes.

| Week | A: new of 12 | A: scanning min | B: new of 22 | B: scanning min | C: new of 40 | C: scanning min |
|---|---|---|---|---|---|---|
| 1 | 12 (100%) | 14 | 22 (100%) | 26 | 40 (100%) | 47 |
| 2 | 9.5 (79%) | 12 | 16.2 (74%) | 20 | 27.3 (68%) | 35 |
| 4 | 7.6 (64%) | 10 | 12.2 (56%) | 17 | 19.5 (49%) | 28 |
| 8 | 6.1 (51%) | 9 | 9.3 (42%) | 14 | 13.5 (34%) | 22 |
| 12 | 5.2 (43%) | 8 | 7.6 (35%) | 13 | 10.4 (26%) | 20 |
| 26 | 3.7 (31%) | 6 | 5.2 (24%) | 10 | 6.2 (16%) | 16 |
| 52 | 3.1 (26%) | 6 | 3.8 (17%) | 9 | 4.2 (10%) | 14 |
| Products added in the year | 232 | | 336 | | 443 | |

**Yes, it falls, and it does not fall to nothing.** The new share halves in the first two months and is
still a sixth to a quarter after a year, for two reasons the model makes explicit: the long tail (things
bought a few times a year are new the first time each is bought) and churn (sizes and brands change). How
sensitive the steady state is (household B, new lines in week 52): with no churn at all, 2.2; churn of
0.5% a week, 3.0; 2% a week, 5.1; a pool of 200 products, 1.9; of 800, 5.6. A small household that
always buys the same things reaches about 2 new a week; one that shops around stays near 5.

**The terminal cost of scanning**, once the catalog is as full as it gets: known items at 15 s are most
of it, not the new ones. For household B in week 52, 18 known lines cost 4.5 min and 4 new ones 4.4 min,
and the 13 lines with no barcode another 5.4. **Scanning is about 10 minutes a week for A, 15 for B and
24 for C, and it stays there**: the per-item cost of a known product, a page load twice over and a
storage choice, is what to cut, more than adding products faster.

## The terminal time cost

The weekly time once most foods are known, for household B (the others scale with their lists):

| | Minutes a week | Share |
|---|---|---|
| Shopping trip: travel and store (not covered) | 90 | 52% |
| Putting away and booking it | 23 | 13% |
| Planning, nutrition, the list | 27 | 16% |
| Pantry upkeep: food off the plan, spoiled food, Mark cooked | 14 | 8% |
| New recipes, keeping it running | 12 | 7% |
| Mid-week changes, leftovers | 7 | 4% |
| **Overhead** | **173** | |
| Cooking, prep and cleanup | 510 (465 to 415 less if `cooking_time` is weighed) | |

So the app's own processes are about 70 minutes of B's 173 (booking, upkeep, planning, recipes, running
it), and the trip it does not cover is 90.

## Where the app's own processes cost most

Ranked by weekly minutes in steady state, household B:

1. **Booking purchases into the pantry, about 15 minutes**, of which the known products' page loads and
   choices are most. Each item is two forms and two full page loads. The page draws every portion on
   hand, works out each one's expiry, and builds the list of every food Buy offers with its unit, on
   every load (`pages/pantry.js`), so it gets slower as the pantry grows. Measured on the owner's
   instance (2026-11-23, read only, five times each, 42 portions on hand): the pantry page takes 1.44 s to
   draw (1.35 to 1.92), the same with an unknown barcode scanned (1.51 s), and it is 158 KB each time, most
   of it the list of 499 foods Buy offers; an HTTPS request across the network adds 0.1 to 0.4 s. So a
   known product spends about 4 s of its 15 waiting for two page loads, and the rest is the person.
2. **Food eaten off the plan, about 8 minutes**: every Use and Count is in grams, which nobody knows for a
   splash of milk or a handful of nuts, so the figure is guessed, or the item is weighed. Grocy counts in
   packages and pieces.
3. **Planning, about 12 minutes**, and only from a terminal: editing a TOML file, a search that takes
   about five minutes, reading the report, committing. For anyone but the owner it cannot be done at all.
4. **New recipes, about 10 minutes a week spread out**, plus the vocabulary when a recipe needs a new
   food: a terminal job with a 2 to 20 minute import (an unchanged reload about 2 minutes, a full load
   12 to 20 in cloud sessions; `cloud-session-notes`).
5. **The shopping list is entered twice.** What was bought from the list is booked again item by item on
   the pantry page, because a tick on the shopping page is only remembered in that browser
   (`docs/todo.md`, "A grocery item checked off goes into the pantry", asked for 2026-11-13).

Also measured on the owner's instance, the same way (median of five, as drawn by Structr, before the network):

| Page | Time to draw | Size |
|---|---|---|
| Week | 0.20 s | 31 KB |
| Recipes | 0.24 s | 30 KB |
| Nutrition | 0.73 s | 396 KB |
| Pantry | 1.44 s | 158 KB |
| Shopping | 1.80 s | 65 KB |

None of the pages is slow enough to matter on its own; the pantry matters because it is drawn twice for
every item booked. A known barcode's look-up was not timed (the timing script's query for a barcode to try
was refused); it draws the same page as an unknown one, so about 1.5 s is expected.

## Steps not covered, and where the time is

| Not covered | Weekly minutes (A, B, C) | Could the app cover it? |
|---|---|---|
| Cooking, prep and cleanup | 275, 510, 625 | Partly: it picks the recipes. `cooking_time`, prep sessions and leftovers are built; quicker recipes and fewer cooks are the lever |
| Travel to the shop | 30, 35, 45 | Partly: fewer trips if the week's list is complete and nothing is forgotten; an order for pickup or delivery removes it |
| In the store | 30, 55, 95 | Partly: a list in aisle order; or the list sent as an online order, which turns 55 minutes in the store into about 10 minutes of checking an order |
| Food eaten off the plan | (now booked by hand) | Partly: breakfasts and snacks as a daily baseline (`private/baseline.toml` exists for supplements) would be drawn from the pantry like a cook |
| Cooks' leftovers as stock | | Planned, not stocked (`docs/todo.md`, "A cook's leftovers as stock") |

**The most time that could be covered is the shopping trip** (60 to 140 minutes a week): the app already
knows exactly what to buy, in whole packages, and only prints it. Cooking is larger, but it is the work
itself; the app's part there is choosing quicker weeks.

## The changes that would save the most

Ranked by minutes saved a week, household B, steady state (estimates). The first three are on the
pantry; together they halve the booking time.

| Change | Saves a week (A, B, C) | Notes |
|---|---|---|
| 1. **Ticking the shopping list books the purchase**, with a default place each product or food is kept, and a "put everything ticked into the pantry" button | 6, 9, 15 | Already asked for (`docs/todo.md`: "A grocery item checked off goes into the pantry"; barcode step 6, "where a product is kept by default"). Only food bought off the list would still be scanned |
| 2. **A booking without a page reload**: the form sent in the background and the row added in place, the camera left open for the next item, a "×2" for packages, the last place kept remembered | 3, 5, 8 | A known product from about 15 s to about 6 s. Also halves the first month |
| 3. **The food chosen for a new product, not typed**: the searchable food picker being built in another thread, and the food suggested from FDC Branded Foods, which carry the same barcodes (barcode step 5) or Open Food Facts' categories | 2, 3, 4 steady; 7, 13, 23 in week 1 | A new product from about 70 s to about 35 s |
| 4. **"Plan the week" on a page** (offered 2026-10-24: a planner container watching for a request) | 5, 7, 10 | And anyone in the household can plan. It also removes most of "keeping it running" from the owner's terminal |
| 5. **Use and Count in packages or pieces**, and planned breakfasts and snacks drawn from the pantry each day | 2, 4, 8 | Grams stay underneath; the page converts as Buy already does |
| 6. **The list in aisle order, or sent as an online grocery order** | 5, 10, 15 (aisle order); 20, 45, 85 (an order for pickup) | Not on the to-do list. The order is the largest single saving in overhead, and depends on a shop's ordering service |
| 7. **`cooking_time` weighed by default** | 0, 145, 150 (cooking, not overhead) | Measured 610 to 465 min for two people. An objective change: the owner's call (CLAUDE.md); listed, not proposed as a default |

With changes 1 to 5, the steady-state overhead falls to about 95, 145 and 205 minutes a week: 20%, 40% and
20% below living without the app, rather than the 5%, 30% and 5% of today. The savings overlap a little (an
item booked by its tick is not scanned, so change 2 then saves less), so these are rounded down.

## What was not checked, and how to check it

- No step of the app was timed with a person. The first check is cheap: book one week's shopping on the
  phone with a stopwatch, writing down the seconds for a known product, a new one and one by name.
- Open Food Facts' hit rate on the owner's shopping is not known (not reachable from cloud sessions, and
  not yet tried on the phone). The model takes 70 s for a new product, found or not.
- The barcode curve rests on assumed popularity and churn, not the owner's receipts. A month of the
  owner's own scans (how many were new each week) would replace it.
- How much is eaten off the plan, and so how many Uses and Counts a week, is a guess.
- Without-app times are estimates against published averages; a household that already plans on paper
  spends less on step 1, and one that shops online spends less on steps 4 and 5.

## Sources

- US Bureau of Labor Statistics, American Time Use Survey 2024, table A-1:
  [bls.gov/tus/tables/a1-2024.pdf](https://www.bls.gov/tus/tables/a1-2024.pdf), and the release of
  2025-06-26: [bls.gov/news.release/archives/atus_06262025.pdf](https://www.bls.gov/news.release/archives/atus_06262025.pdf)
- USDA ERS, time spent shopping for groceries (43.2 min in 2004-07, 46.0 in 2014-17, on days people shop):
  [ers.usda.gov, Amber Waves, April 2020](https://www.ers.usda.gov/amber-waves/2020/april/more-americans-spend-more-time-in-food-related-activities-than-a-decade-ago)
- Dalhousie University survey, 2018 (43 min a visit in the US, 32 in Canada):
  [BNN Bloomberg](https://www.bnnbloomberg.ca/how-fast-do-you-shop-canadians-average-32-minutes-at-grocery-store-study-finds-1.1171111)
- FMI, U.S. Grocery Shopper Trends 2026 (trips a week):
  [fmi.org](https://www.fmi.org/newsroom/latest-news/view/2026/05/20/fmi-s-signature-research-examines-the-evolving-physical-store-experience)
- Yu and Jaenicke, "Estimating Food Waste as Household Production Inefficiency", American Journal of
  Agricultural Economics, 2020 (31.9%):
  [Penn State](https://www.psu.edu/news/research/story/study-suggests-us-households-waste-nearly-third-food-they-acquire)
- Deciding what to eat, OnePoll for Dolmio (a commissioned poll):
  [The Scotsman](https://www.scotsman.com/read-this/adults-spend-just-under-40-hours-a-year-deciding-what-to-eat-4588095)
