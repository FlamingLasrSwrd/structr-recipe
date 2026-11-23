# Plans for the time study's suggestions

**Status: plans, for the owner to choose from (2026-11-23).** The owner asked, after reading
`docs/time-study.md`: "Make a plan for each of the suggestions." Nothing here is built. Each plan says
what it would do, in what stages, which files it touches, whether it changes the schema, how it would be
checked (the project's rule: the pages and Python do the same thing, and a check compares them), what the
owner has to decide, and what it should save. The savings are the time study's estimates for its three
placeholder households (A one adult, B two adults with one tracking nutrition, C a family of four), in
minutes a week once most barcodes are known.

## The order proposed

| # | Plan | Saves (A, B, C) | Size | Schema change | Waits on the owner for |
|---|---|---|---|---|---|
| 0 | Measure one real week first | | an hour of the owner's time | no | doing it |
| 1 | A shopping-list tick books the purchase | 6, 9, 15 | medium | no | what an untick does |
| 2 | Bookings without a page reload | 3, 5, 8 | medium | no | bookings written as the signed-in person |
| 6a | The shopping list in store order | 5, 10, 15 | small | no | the order of the owner's shop |
| 3 | The food for a new product chosen, not typed | 2, 3, 4 (7, 13, 23 in week 1) | mostly done | no | whether the FDC table is worth it |
| 4 | "Plan the week" on a page | 5, 7, 10 | large | probably not | where the planner runs; proposals in the graph |
| 6b | Online grocery ordering | 20, 45, 85 | staged: small to large | no | which shop; sending the list out |
| 5 | Use and Count in packages, and the daily baseline drawn from stock | 2, 4, 8 | medium | no | what "as planned" books |
| 7 | The week's cooking time weighed | cooking: 0, 145, 150 | none to small | no | the objective (the owner's call) |

1 and 2 belong together: both change how food gets into the pantry, and 2 makes 1's taps instant. 6a is
cheap and independent. 6b's first stage is cheap too, and its later stages make 1's ticks unnecessary for
an order placed online.

## 0. Measure one real week first

Every per-item time in the study is an estimate. Before building, the owner books one week's shopping
from the phone with a stopwatch (or a screen recording), writing down, for a handful of each: a product
the instance knows, a new product (with the type-ahead picker of PR #13 installed), and food bought by
name; and for the week, how many lines were new, how many Uses and Counts were needed, and how long the
planning took. That replaces the study's guesses with the owner's own numbers and may reorder this list.
A small form to record it in (`private/`) is enough; nothing to build.

## 1. A shopping-list tick books the purchase

Asked for 2026-11-13 (`docs/todo.md`, "A grocery item checked off goes into the pantry"). Today a tick on
the shopping page is only remembered in that browser, and every item is entered again on the pantry page.

- **Stage 1: "Bought" books the line.** Each line of the shopping page gets a tick that is a booking (a
  token per line, so a reload books nothing twice), writing what `pantry.buy` writes: the food on the line,
  the amount the line buys (its whole packages times the package size, which the list already works out,
  `docs/packages.md`), and where it is kept. A line can be changed before it is ticked (another amount, a
  product chosen from those of the food, a scan that matches the line by its food).
- **Where it is kept, worked out, not asked** (barcode step 6, "where a product is kept by default"):
  frozen foods in the freezer; a food FoodKeeper gives a pantry time for, unopened, in the pantry; anything
  else in the fridge (`data/foodkeeper/foodkeeper.json` already has those times for the foods that name a
  FoodKeeper product). A product may carry its own default, set the first time it is moved. Computed, not
  stored, except a product's own choice.
- **Stage 2: "Put everything ticked into the pantry"**, one button, for a list ticked in the shop (ticks
  remembered as now, then booked together, each line with its own token).
- **Untick.** Undoing a purchase needs the journal that is not built (`docs/todo.md`, "A pantry journal,
  and undoing a booking"). Until then: an untick within a few minutes removes what that booking made (it
  has its token, and nothing has drawn on it yet); later, a Use or a Count corrects it. **The owner's
  decision.**
- **Files:** `mealplanner/pantry.py` (a `buy_line` from a shopping line) and its twin in
  `pages/lib/50_pantry.js` and `90_shopping.js`, `pages/shopping.js`; a storage rule shared by the
  pantry's Buy, which would then default to it too.
- **Checks:** `tests/` over the in-memory graph (amount and storage worked out by hand for a few lines);
  `tools/check_bookings.py` books a line through the page and through Python and compares them;
  `tools/check_pages.py` keeps comparing the list. Break the storage rule on purpose and see the test fail.
- **Saves** 6, 9 and 15 minutes a week (every item bought from the list no longer scanned), and more in
  the first month, when most items would otherwise be new barcodes.

## 2. Bookings without a page reload

Today each booking is a form sent to the pantry page, which then draws itself again: 1.44 s to draw and
158 KB each time on the owner's instance (measured 2026-11-23), twice per known item, and the camera
closes with every reload.

- **Stage 1: book through the method, not the page.** The `bookPantry` method exists (`methods/`,
  `docs/methods.md`): the same bookings, called with `POST /structr/rest/bookPantry`. The page sends its
  forms with `fetch` and the signed-in session, reads the method's answer, and adds or changes the row in
  place. The forms stay as they are underneath, so a browser without JavaScript still books by reloading.
  A barcode look-up needs a small read-only method (`findProduct`, from `pages/lib/55_products.js`). Adding
  a product stays the page's alone (it writes shared vocabulary as the superuser), so a new product still
  reloads once.
- **Stage 2: scanning in a row.** The camera stays open. A known product read shows a small card: the
  product, packages with − and + (no typing grams for two cans), where it is kept (stage 1 of plan 1's
  rule, else the last place chosen), and **Add**; then the camera reads the next one.
- **Stage 3: a lighter page.** The list of every food Buy offers (499 foods, most of the 158 KB) moves into
  a file served once and kept by the browser, as the camera's files are (`pages/files/`), so a page that
  is drawn again sends a fraction of it.
- **The decision:** the method books **as the signed-in person**, so what it writes belongs to their
  household and is visible to it, where the page books as the superuser (`docs/pages.md`). That is the
  direction of Path S (`docs/architecture-decision.md`), and `tools/check_households.py` already checks it,
  but the owner's instance would then hold bookings made both ways. Each member needs the method's grant.
- **Files:** `pages/pantry.js` and a new script in `pages/files/`, `methods/findProduct.js`, the grants in
  `tools/install_methods.py`.
- **Checks:** the browser tests run the page in Chromium as `tests/test_pantry_camera.py` does, with the
  method answered by the test: a booking made, the row changed, a refused booking shown, a reload booking
  nothing; `tools/check_bookings.py` compares a booking through the method with one through the page.
- **Saves** about 9 s of a known product's 15, so 3, 5 and 8 minutes a week, and half the first month's
  scanning.

## 3. The food for a new product chosen, not typed

Mostly done: PR #13 (merged 2026-11-23, after the study) finds the food as it is typed and offers
**Likely:** foods from Open Food Facts' categories to tap. It needs `tools/install_pages.py` on the
owner's instance.

- **Next: measure it** (plan 0): how often the right food is among the likely ones, on the owner's own
  first weeks of scanning.
- **Then, only if that is often wrong: a second suggestion from FDC Branded Foods** (barcode step 5), which
  carries the same GTINs and a category for each. A table from category to the vocabulary's foods, built
  offline from the FDC zip that `tools/package_extract.py` already reads, is small; the table from each
  GTIN to its category is not (about 391,000 US GTINs, around 10 MB), so it would be pinned only for the
  categories that map to a food, or looked up from the FDC API by a tool. **The owner's decision**, after
  the measurement.
- **Also: products known before they are scanned.** An order placed online (plan 6b, stage 2) arrives with
  each item's barcode, so its products can be added from the order, and nothing in it is new at the shelf.
- **Saves** 2 to 4 minutes a week once the catalog is full, and 7, 13 and 23 minutes in week 1.

## 4. "Plan the week" on a page

Offered 2026-10-24 (`docs/todo.md`, "A Plan the week button and a preferences page"; `docs/self-hosting.md`
step 3). Today planning needs a terminal on the computer that runs Structr: edit `private/week.toml`, run
`tools/plan_week.py` (about five minutes of search), read the report, commit.

- **Stage 1: the week's settings on a page.** A form for what the week file says now (the days, the meals
  and who eats them, what to cook, prep sessions, the week's weights), saved on the week's MealPlan, as its
  weights already are. The defaults are last week's.
- **Stage 2: a planner that watches.** A small service beside Structr on the same computer (a container in
  the compose file, or a service on the host) notices a request to plan, runs the planner's library
  (`mealplanner/planning/`, as `tools/plan_week.py` does), and writes the proposal back. One solve at a time,
  with the time limit, within the memory caps. It needs no open port: it watches the graph.
- **Stage 3: review and commit on a page.** The week page shows the proposal (its meals, nutrients and
  cost, as the terminal report does) with **Commit** and **Plan again**. The proposal is stored where a page
  can read it: the simplest is the proposal file the tool already writes (`planning/proposal.py`), kept as a
  Structr file beside the week, so no schema change; proposed entries in the graph would be another
  modeling question.
- **Decisions:** where the planner runs; who may ask for a plan (each request records who asked, checked
  when it runs: `docs/self-hosting.md`'s table); whether a proposal lives in the graph.
- **Checks:** a request through the page and the same week through `tools/plan_week.py` give the same
  problem (the planner's JSON contract, `planning/contract.py`, makes that comparable); the watcher's own
  tests with a stand-in instance.
- **Saves** 5, 7 and 10 minutes a week of attention, and lets anyone in the household plan. It is also the
  backend `docs/todo.md` asks for ("One backend for what the pages compute and book"), so later pages can
  ask Python rather than repeat it in JavaScript.

## 5. Use and Count in packages, and the daily baseline drawn from stock

Today a Use or a Count is typed in grams, which nobody knows for a splash of milk or half a jar, so food
eaten off the plan is guessed, weighed, or left until the pantry drifts.

- **Stage 1: amounts as people say them.** Use and Count take a number of packages or pieces (from the
  product's package size, the food's weight per item, or its usual unit, as Buy already picks one), and
  Count offers "full, ¾, ½, ¼, empty" of what the portion held when bought. Underneath it is still grams
  (the conversion Buy already does), recorded as an estimate rather than a weighing where the measurement
  statuses allow it.
- **Stage 2: what is eaten every day, drawn from stock.** Breakfasts, snacks and drinks the household has
  every day are written as baseline recipes (`private/baseline.toml` holds supplements this way now). A
  button on the week page, **Yesterday as planned**, books every planned meal not yet marked and the
  day's baseline in one go, so the daily food no longer needs a Use. Nothing is booked without someone
  pressing it.
- **Decisions:** which foods count as daily; whether "as planned" may book a whole day at once.
- **Files:** `pages/pantry.js`, `pages/lib/50_pantry.js` and `mealplanner/pantry.py` (amounts), `pages/week.js`
  and `pages/lib/70_menu.js` with `mealplanner/menu_changes.py` (the day's button).
- **Checks:** `tools/check_bookings.py` books "½ of a jar" and a day as planned both ways; tests with the
  grams worked out by hand.
- **Saves** 2, 4 and 8 minutes a week, most in the family, whose breakfasts and snacks are most of what is
  eaten off the plan.

## 6a. The shopping list in store order

The list is ordered by the day each food is first needed, which suits cooking and not walking a shop.

- **Stage 1: sections from data the instance has.** Each food's FoodKeeper category (Dairy Products & Eggs,
  Produce, Meat, Shelf Stable Foods, Baked Goods, ...) is already pinned in
  `data/foodkeeper/foodkeeper.json` for the foods that name a FoodKeeper product; the few that do not get a
  section in `data/vocabulary.toml`. The shopping page groups by section, keeping the day first needed as a
  column, and asks `?order=day` for today's order.
- **Stage 2: the owner's own shop.** The order of the sections in the owner's shop, as a small private
  profile (as `private/packages.toml` is), so the list walks the shop from the door.
- **Files:** `mealplanner/shopping.py` and its twin `pages/lib/90_shopping.js`, `pages/shopping.js`,
  `tools/shopping_list.py`.
- **Checks:** `tools/check_pages.py` keeps comparing the list with Python; a test with a hand-made shop order.
- **Saves** about 5, 10 and 15 minutes a week of walking back across the shop (an estimate). Not needed for
  an order placed online.

## 6b. Online grocery ordering

Asked for 2026-11-23 ("Add online grocery ordering integration to the todo list"; `docs/todo.md`). The
largest saving in the study: the app knows exactly what to buy, in whole packages, and only prints it.
Ordering online turns 30 to 95 minutes in the shop into about 10 of checking an order, and pickup or
delivery cuts the trip.

- **Stage 0: the list, ready to paste.** A "Copy list" button and a plain-text and CSV export from the
  shopping page and `tools/shopping_list.py`: each line as a shop's search understands it ("2 × 15 oz
  canned black beans"), and, for a shop whose search has an address, a search link per line, built from a
  template in a private profile. Works with any shop, sends nothing anywhere until the person clicks.
- **Stage 1: a shopping list on Instacart.** Instacart's Developer Platform takes a list of line items
  (a name, a quantity and a unit) and answers with a link to a shopping list page, where the person picks
  a store near them, sees what it has, and adds it to their cart (`POST /idp/v1/products/products_link`;
  a key from Instacart's developer sign-up; the US and Canada). A tool (`tools/order_list.py`) makes the
  link from the week's list, so the key stays in `.env` and the instance itself still never calls out.
  Matching an item to a product is left to Instacart and the person.
- **Stage 2: a shop with a cart API** (Kroger's public API is one: a product search, then
  `PUT /cart/add` with each item's UPC and quantity, signed in by the shopper through OAuth). Here the
  products the pantry already knows (their GTINs, J38) go into the cart exactly; a food with no product is
  searched once, the person picks, and that choice is saved as a product of the food, so next week it is
  exact too. The order's items then go into the pantry from the order (plan 1's "book everything", with
  the amounts the shop confirms), and nothing needs scanning at home.
- **Decisions:** which shops the owner uses and which have an API there (Kroger's banners are US only;
  Instacart covers many US and Canadian chains); whether delivery fees are worth the time; and **sending
  the household's shopping list to a third party**, which the project has avoided so far (only one barcode
  at a time goes to Open Food Facts, from the phone).
- **Checks:** the line items built from a shopping list are tested offline against hand-written
  expectations; the API calls against a stand-in server (as Open Food Facts was), then once for real by
  the owner, with the key.
- **Saves** about 20, 45 and 85 minutes a week with pickup (the store time, and part of the trip), more
  with delivery; stage 0 alone only saves typing a list into a shop's site.

## 7. The week's cooking time weighed

Built and off by default: `[weights] cooking_time` in the week file (the owner's decision, 2026-10-24).
Measured on the owner's recipes for two people: 610 minutes of cooking at 0, 465 at 0.5 to 2, 415 at 4,
every week meeting every hard target (`docs/optimizer-design.md` §12). Changing its default is an
objective change, and the owner's call; nothing here proposes doing that silently.

- **Stage 1: try it, no code.** Set `cooking_time = 0.5`, then `1`, in `private/week.toml` for the next two
  weeks, and judge the weeks it proposes. If they are good, leave it in the week file.
- **Stage 2, optional: compare in one run.** `tools/plan_week.py --compare cooking_time=0,0.5,1` would plan
  the week once per value and print each one's cooking minutes, score and nutrients side by side, saving
  three separate five-minute runs. It changes no objective.
- **Then the owner decides** whether a default other than 0 belongs in the code (`docs/optimizer-design.md`
  §4.5).
- **Saves** up to about 145 minutes a week of cooking for two people, the largest figure here, at no cost in
  overhead.
