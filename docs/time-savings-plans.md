# Plans for the time study's suggestions

**Status: plans, for the owner to choose from (2026-11-23; revised the same day on the owner's answers).** The owner asked, after reading
`docs/time-study.md`: "Make a plan for each of the suggestions." Nothing here is built. Each plan says
what it would do, in what stages, which files it touches, whether it changes the schema, how it would be
checked (the project's rule: the pages and Python do the same thing, and a check compares them), what the
owner has to decide, and what it should save. The savings are the time study's estimates for its three
placeholder households (A one adult, B two adults with one tracking nutrition, C a family of four), in
minutes a week once most barcodes are known.

## The order proposed

| # | Plan | Saves (A, B, C) | Size | Schema change | Waits on the owner for |
|---|---|---|---|---|---|
| 1 | A shopping-list tick books the purchase: **to build** (the owner, 2026-11-23) | 6, 9, 15 | medium | no | how an undo is recorded (`docs/todo.md`, "Undo a booking") |
| 2 | Bookings without a page reload | 3, 5, 8 | medium | no | none: bookings for the household, naming who (decided 2026-11-23) |
| 8 | Scanning an item as it is used | 1, 2, 4 | medium, after 2 | no | none: decided 2026-11-23 |
| 6a | The shopping list in store order | 5, 10, 15 | small | no | the order of the owner's shop |
| 3 | The food for a new product chosen, not typed | 2, 3, 4 (7, 13, 23 in week 1) | mostly done | no | whether the FDC table is worth it |
| 4 | "Plan the week" on a page | 5, 7, 10 | large | probably not | where the planner runs (options below); proposals in the graph |
| 5 | Use and Count in packages, and the daily baseline drawn from stock | 2, 4, 8 | medium | no | what "as planned" books |
| 7 | The week's cooking time weighed | cooking: 0, 145, 150 | none to small | no | the objective (the owner's call) |
| 6b | Online grocery ordering: **later** (the owner, 2026-11-23: "not a priority") | 20, 45, 85 | staged: small to large | no | which shop; sending the list out |

1 and 2 belong together: both change how food gets into the pantry, and 2 makes 1's taps instant. 8
builds on 2 for food going out. 6a is cheap and independent. 6b waits (the owner, 2026-11-23).

**Measuring first was dropped:** the owner, 2026-11-23: "Estimates are fine for now."

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
- **How a purchase is recorded now** (`docs/pantry.md`, "What each action writes here"; data-model.md
  §4.1.1, §5): a `Process` of kind *Purchase* at a `TemporalRegion`, naming the Person who booked it
  (`wasAssociatedWith`); a `PortionOfSubstance` that begins to exist during it, `locatedIn` a
  `ContainerObject` with its storage condition and *Sealed*; and the portion's Mass `Quality` with an
  `observed` `Measurement` of the amount bought. Five or six nodes, every one named after the booking's
  token ("Purchase 3f9a -- Milk"), which is what makes a form sent twice write nothing new.
- **Can it be undone?** Not today: nothing on the pages or in the tools takes a booking back. The model
  leaves that to the application (data-model.md §12: "Application-level undo is edit history, not domain
  semantics"). Because every node a purchase made carries its token, **undoing a purchase that nothing has
  drawn on yet is easy**: delete the nodes of that token, once no Use, cook, discard or Count refers to its
  portion. After something has drawn on it, the purchase happened and stays; a Use or a Count corrects
  the amount, which is the compensating booking `docs/todo.md` describes ("A pantry journal, and undoing
  a booking"). So an untick soon after the tick removes that purchase; a later one is refused with the
  reason, and points to Use, Count or Discard. **The owner's decision.**
- **An alternative to ticking: scanning the receipt** (the owner, 2026-11-23; `docs/todo.md`, "Scanning a
  grocery receipt", a later build). A photo of the receipt, read as text, each line matched to a product or
  food and booked as plan 1's "book everything" does. It catches what was bought off the list too, and
  each line's price paid (`PriceObservation`, J27, which nothing writes yet). What makes it hard: a
  receipt names items in a shop's own abbreviations ("GV WHL MLK 1G"), so each line is matched by hand the
  first time and remembered for that shop after, the same falling curve as barcodes; reading the text
  well needs either a reader in the browser (Tesseract.js, as the camera's reader is served from the
  instance) or a vision service, which sends the receipt out. A shop's emailed or in-app receipt, where it
  carries full names or barcodes, is easier than a photo.
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
- **Households and people** (the owner, 2026-11-23: "Bookings need to be specific to the household, but
  tracking users would be better"). Both, and this is the way to both:
  - *Who booked it* is recorded already for a purchase, a use, a discard and a cook: each `Process` is
    `wasAssociatedWith` the signed-in Person (since 2026-11-04, pages and methods alike). A Count, an
    Open and a Move write no Process, so they name no one; giving each a Process of its own
    (`docs/verification-and-sharing.md` §3.1) closes that.
  - *Whose it is:* today a page books as the superuser (`$.doPrivileged`) and marks what it writes visible
    to every signed-in user, so on one instance every account sees every household's pantry. The methods
    (`bookPantry` and the rest) book **as the caller**, private to the caller's household and granted to
    its Group; `tools/check_households.py` checks two test households cannot see or book on each
    other's. That is **Path S** (`docs/architecture-decision.md`, the owner's decision of 2026-10-26: the
    work a request does runs in Structr's JavaScript methods next to the data, under Structr's own
    accounts and access control; Python keeps the planner's search and the batch imports). Stages 1 to 3
    are built; **stage 5**, access control on the real data (a migration marking the owner's data as the
    household's, the pages without `$.doPrivileged`), is not. Booking through the methods here is a step
    of stage 5 (the owner, 2026-11-23: "Everything that can be specific to a user, should be"; being built
    in its own thread); the migration of what is already there comes with it, so the instance does not hold
    bookings made both ways for long. Each member needs the method's grant.
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
- **Where the planner runs.** Not on a phone or in a browser: CP-SAT is native code, and a week takes
  about five minutes of search with several hundred megabytes. So on a server, and the planner already has
  a seam for it: `tools/plan_problem.py` plans from a problem file (the JSON contract) and touches no graph,
  so the search can run anywhere a problem can be sent. The options (from `docs/self-hosting.md` step 3 and
  "Security of the backend choices"):

  | Option | How | For | Against |
  |---|---|---|---|
  | **A watcher beside Structr** (recommended) | a container in the same compose file, or a service on the computer, notices a request in the graph, plans, writes the proposal back | no open port, no credentials between services; the household's data never leaves the computer; nothing to pay; the computer already has to be on for the pages (8 cores, 24 GB: a solve fits beside the stack) | the request waits for the watcher's next look (seconds); one solve at a time |
  | A planner web service the page calls | Python on the stack's own network, called by Structr | an answer in the same request | a five-minute call holds a page open; a second service to secure (a shared secret, its own account) |
  | Structr runs a registered script (`exec()`) | Python, the repository and OR-tools inside Structr's image | no extra container | a Python process per call; changing Structr's image; arguments from a page are an injection risk |
  | Structr's scheduler | a fixed job, say Sunday evening plans next week | nothing to press | runs as an admin with no permission check; no request from a person |
  | A worker elsewhere | the problem file sent to a cloud machine or function, the plan sent back | for a weak home computer, and the shape a hosted service would use (a queue of workers) | the problem holds the household's data, which then leaves the house; costs money; a network path to secure |
  | The search in JavaScript inside Structr | a port | no Python at all | CP-SAT has no JavaScript form; the dependency-free search alone is weaker; its 256 tests would have to be redone |

  The watcher first, with the scheduler as an option on top (a standing request every Sunday). Under Path
  S it calls an `exportWeek` method for the problem and a `commitWeek` method to write the plan, as the
  person who asked (`docs/architecture-decision.md` §5a; stage 4's JavaScript half, not built); until those
  exist it can use the Python extract and commit, as `tools/plan_week.py` does.
- **Decisions:** the watcher or another option; who may ask for a plan (each request records who asked,
  checked when it runs: `docs/self-hosting.md`'s table); whether a proposal lives in the graph.
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

## 6b. Online grocery ordering (later)

**Not a priority** (the owner, 2026-11-23: "Add it as a feature to be built later and move on"). Kept here
as planned. Asked for 2026-11-23 ("Add online grocery ordering integration to the todo list"; `docs/todo.md`). The
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

## 8. Scanning an item as it is used

Asked to be looked into by the owner (2026-11-23): "if I add a splash of milk to my coffee this morning, I
can scan the barcode and select '30 ml' from the use menu." Food eaten off the plan is the pantry's
upkeep cost in the time study, and today booking it means finding the row on the pantry page, opening
**Change**, and typing grams.

- **What the scan box would do.** A switch beside it, **Buy** or **Use** (it stays on the last one chosen).
  In Use, a scan reads the product as now (`findProduct`), and shows a small card: the food, which portion
  it draws from, a row of amounts to tap, and **Use**. Nothing about a product changes: a product is stock
  of its food, so a scan of any package of that food finds it.
- **Which portion.** The opened one first, then the soonest to expire, then the oldest, as Grocy does
  (the carton being poured is the open one; a cook draws soonest to expire, which agrees once one is
  open). The card names it, and a tap changes it.
- **The amounts offered:** the ones this household used before for that food (worked out from its earlier
  Uses, computed, not stored: the second time, "30 ml" is there to tap), then the food's usual serving
  (240 ml for milk, from `serving` in `data/vocabulary.toml`), then kitchen measures (a teaspoon, a
  tablespoon, a quarter cup) and "the rest". A volume is weighed through the food's density, as Buy
  already converts; a food with none is offered in its own units only.
- **Opened as it is used.** The first Use of a sealed portion marks it *Opened* (Grocy does the same), so
  the expiry changes to the opened shelf life without a separate **Open**. Expiry still runs from the
  purchase (`docs/pantry.md`, finding 2).
- **A barcode no product has**, scanned in Use: "Add a product" as now, or "use it as" a food chosen
  from the picker, without making a product.
- **A food with no barcode** (a banana, the butcher's mince): the same card, reached from a short list of
  the foods used most often lately, with no scan at all; for the most frequent, that list may well be
  faster than a scan.
- **Time:** a scan and two taps, about 8 s per use with plan 2's bookings without a reload (about 15 s with
  today's), against about 25 s through **Change** now, and against nothing when it is left to a monthly
  Count, which then costs its own time and leaves the pantry and the shopping list wrong in between. For
  household B's eight uses a week, about 1 minute instead of 3, and a pantry that is right.
- **Files:** `pages/pantry.js` and the scan script in `pages/files/`; `pages/lib/50_pantry.js` and
  `mealplanner/pantry.py` (a Use of a food, choosing its portion, the amounts used before); plan 2's
  method calls. No schema change: a Use writes what it writes now.
- **Checks:** `tools/check_bookings.py` books "30 ml of milk" from a scan both ways and compares the
  nodes, and the portion chosen when one is opened and another is not; the browser test scans in Use as
  `tests/test_pantry_camera.py` scans in Buy; the amounts offered tested over a hand-made history.
- **Decided by the owner, 2026-11-23:** the first Use of a sealed item marks it opened. The amounts
  offered are the person's own, and where the person has none, their household's, then the food's across
  every user ("the remembered amount should be available as a user, household, and food with inheritance
  across all users"): three levels resolved the way defaults are (`mealplanner/defaults.py`), the food's
  level shared with everyone, as a new product is (`docs/todo.md`, "New shared data reaches every user at
  once"). It needs the per-person and per-household data of Path S stage 5, being built in its own thread.
