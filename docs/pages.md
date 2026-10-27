# Pages: the week, the recipes, nutrition and the pantry in a browser

Structr serves four pages and a recipe page from the planner's own graph (the owner's choice,
2026-10-22: week view, recipe book, week's nutrition, pantry). They read; two of them also book
what happens to the pantry (the owner's request, 2026-10-23): the pantry page's forms and the week
page's "Mark cooked" (docs/pantry.md).

| Page | Address | What it shows |
|---|---|---|
| Week | `/structr/html/week[/<MealPlan id>]` | a committed week's meals by day: cook or leftovers, servings cooked, each person's servings, and when to start a dish made ahead (J29). **Mark cooked** on a meal not yet cooked takes its ingredients out of the pantry, soonest to expire first, and says what the pantry did not hold (`pantry.cook`). **Didn't make it** (or **Won't make it**, for a meal still to come) skips a meal not cooked, with what was eaten instead: a recipe from the book (suggested as you type) is planned in its place for the same people and servings; anything else is kept in its words, and leaves those people's nutrition for the day unknown; nothing frees the meal. Skipping a cook skips the meals that were to eat its leftovers. **Undo** plans a skipped meal again. When meals still to come are free, the page says to plan them with `tools/plan_week.py` (`menu_changes.skip`, `unskip`; data-model.md J34) |
| Shopping | `/structr/html/shopping[/<MealPlan id>][?prices=<level>]` | a committed week's shopping list, as `tools/shopping_list.py` makes it: by the day each food is first needed, what to buy (a count where the recipes count it), what is on hand, the cost at a price level (default `Home prices`), what the pantry covers and what a recipe gives no amount for; a tick box on each line, remembered in that browser. Stock policies' levels are not applied here (the tool applies them; the page says so when one exists) |
| Recipes | `/structr/html/recipes[?meal=Breakfast]` | the book the planner chooses from (no baselines, nothing retired): meal types, minutes, difficulty, servings, and energy, protein, fibre and sodium a serving where targets are about them |
| Recipe | `/structr/html/recipe/<Plan id>` | one version: where it came from, its facts, its ingredients and amounts step by step, and every stored figure per serving with what it rests on. A source's instructions are not stored; **How to make it** writes each step as a sentence of our own from its facts (method, ingredients and amounts and what may stand in, tools and their heat, a capability as the tools that can give it, minutes, order, doneness: `mealplanner/instructions.py`, `pages/lib/75_instructions.js`, J35, J36, J37). A **Cook in the week of ...** button asks for the recipe in the next week to plan, and takes it back (`mealplanner/requests.py`, data-model.md J33); the recipe book lists what that week has asked for |
| Nutrition | `/structr/html/nutrition[/<MealPlan id>]` | each of the week's targets judged at its own scope, per person: met, under, over or unknown, per day (and per meal or week where a target is scoped so), and a daily target's **week total**: its days added up, judged against its range times the days with meals (`nutrition_scope.week_totals`; the owner's request, 2026-10-24) |
| Pantry | `/structr/html/pantry` | every portion on hand, how much, when it was weighed, and when it expires, soonest first. **Buy** adds a portion (a food, an amount in any unit that converts to grams, where it is kept, its perishability class); each portion's **Change** has **Use**, **Count** (a stock take), **Open**, **Freeze** (or **Move to fridge**) and **Discard** |

A week page without an id shows the latest week with entries, and links the others. The week and
nutrition pages show **committed** weeks only: a proposed week exists nowhere until
`tools/plan_week.py --commit` writes it.

## How they are built

Each page is one server-side script: the engine code in `pages/lib/` (shared with the Structr methods,
`docs/methods.md`), then `pages/common.js`, then `pages/<name>.js`, run by Structr's
JavaScript engine (GraalJS) as the signed-in user, inside a `Page > html > (head, body)` tree that
`tools/install_pages.py` creates. The scripts work their figures out again, as the Python modules do,
each function naming the one it follows: `nutrition_scope.nutrition_report` and its helpers,
`inventory.current_magnitude` and `instance_expiration`, `shopping.shopping_list`, `defaults.resolve_default`,
`unit_conversion.convert_to_grams`. That is the cost of pages served by Structr: Python cannot run
there. `tools/check_pages.py` is the guard: it renders every page, reads the data block each prints
(`<script id="page-data">`), and compares it with Python's answer for the same graph.

```bash
python3 tools/install_pages.py      # install, or replace, the pages
python3 tools/check_pages.py        # what they show, against Python
```

**Bookings.** A form sends `?do=<booking>&token=<one per form>` to its page, and the page books it
before it draws itself, as `mealplanner/pantry.py` does, function by function (`pages/lib/40_bookings.js`,
`50_pantry.js`, `60_requests.js`; `pages/week.js`). Every node is found by name before it is
created, so a form sent twice, or the page reloaded, writes nothing new; the page then clears the
address. It writes as the superuser through Structr's `$.doPrivileged`, so a household member's
booking needs no write grant of its own, and every node states its visibility. Each booking prints a
data block (`<script id="booking-data">`) saying what it wrote. `tools/check_bookings.py` is the guard
for these, on a development or throwaway instance only (it writes, then removes what it wrote): it
makes every booking once through the page and once through Python and compares the nodes, field by
field, and what the inventory engine then says of both portions.

```bash
python3 tools/check_bookings.py     # the pages' bookings, against Python's (not on the owner's instance)
```

Two things the pages do not do that Python does:
- **A recipe with no stored figure** shows none; Python would work it out from the ingredients.
  `tools/calculate_recipe_nutrition.py` stores them, and the importers keep them current (J28).
- **A unit that needs a density or weight per item** is converted (the pages resolve those defaults
  as Python does); a unit outside `unit_conversion.UNIT_TABLE` is shown as not convertible.

## Signing in

Everything the pages read is visible to signed-in users only, and so are the pages. Verified on
Structr 6.0.0 (throwaway instance, 2026-10-22):
- The superuser cannot sign in to them: `POST /structr/rest/login` answers "login with superuser not
  supported". Whether a sign-in to the admin UI (`/structr/`, over its websocket) also opens the pages
  is not known: imitating it from a script was refused (403), and it was not tried in a browser.
- A Structr user with a password can, through a sign-in page (`--login` installs one at
  `/structr/html/login`, and the grant that lets an anonymous visitor post to `/structr/rest/login`).

So reading the pages in a browser needs a user with a password. The owner decided (2026-10-23) that
the pages need no more security than that for now, the instance being local and behind a firewall:
`install_pages.py --login` installs the sign-in page with its grant, and the owner makes the account
with `tools/create_login.py`, which asks for a name and a password. A household person's name gives
that `Person` a password (a Person is also a Structr account, data-model.md K1), so they sign in as
themselves: the owner chose that for Elijah (2026-10-23). Any other name makes a separate `User`.
Claude does not make an account: it and its password are the owner's to type.

```bash
python3 tools/install_pages.py --login
python3 tools/create_login.py
```

Then sign in at `/structr/html/login`; it goes on to the week.

## Checked at scale (2026-10-23, throwaway instance)

With 1,001 recipes, a committed three-day week for two people and a pantry of 43 portions (12 given
shelf lives), `tools/check_pages.py` found **0 differences** on every page: 9 meals, 168 target groups,
all 1,001 recipes over 11 pages, 43 portions with their expiry. Rendering times there:

| Page | Time |
|---|---|
| Week | 0.6 s |
| Recipes (100 a page, or one meal type) | 5 to 7 s |
| Recipe | 0.5 s |
| Nutrition | 1.8 to 2.2 s (10.6 s before each recipe's figures were read once per page) |
| Pantry | 1.6 s |

Following a relationship costs about 1.8 ms in a page script, so the recipe book reads sparingly: the
meal filter through the meal type's own list, facts only for the recipes shown, and each nutrient's
figures in one query matched to their recipe by name, falling back to the recipe's own list.

A test user (with a generated password, deleted afterwards) signed in through `/structr/rest/login`
with the grant `--login` installs, and read every page with its session. Signed out, a page answers
404; the sign-in page answers to anyone.

## Verified mechanics (structr-cheatsheet.md has the details)

- Every element must state its `tag` (`html`, `body`, ...); without it Structr 6 renders nothing at all.
- Deleting a `Page` leaves its elements behind; the installer deletes every element of a page first.
- A `${{ ... }}` script block may hold nested braces and template literals; `$.print` writes raw HTML in a
  `text/html` Content node; `Intl.DateTimeFormat` with a `timeZone` works; `$.request.<name>` is a query
  parameter and `$.current` the node named after the page in the address.

## Bookings checked (2026-10-24, the development instance)

`tools/check_bookings.py` found every booking the same both ways: buy (600 g, 5 days to expiry as
Fresh Meat in the fridge), the same purchase sent again (nothing written), use (450 g left), count
(420 g), open (2 days left), freeze (90 days: opened, in the freezer), discard (none left), and a cook
of a two-serving braise drawing 500 g of chicken; and, later that day, a recipe asked for in the next week to plan from its page, asked again (nothing written) and taken back, through the page and through `mealplanner/requests.py` alike. and a week's menu changed
(a cook skipped with another recipe eaten instead, its leftover meal skipped with it, undone, then
skipped with takeout instead) on two weeks alike, the same both ways. The nutrition page and
`nutrition_report` agreed on a meal eaten instead (the day unknown) and on one skipped with nothing
instead (the day short), once the development instance had stored figures per serving. `$.doPrivileged` exists on Structr 6.0.0, so the
pages book as the superuser for whoever is signed in.

**One booking at a time (2026-10-26, the third review's #9, first in its order of work).** Until then a page's write
committed a moment (about 0.3 s) after the page answered, in the page's own transaction, and two bookings
at once each looked for their nodes before either had committed: one purchase form sent four times at
once made four Processes of one name, and all four pages said "booked"; two recipes asked for in one week
at once made two MealPlans of one name; and a commit refused by a validator, after the page had answered,
was reported as booked. Now each booking runs in a transaction of its own (`$.doInNewTransaction`),
which first writes to one lock node, so a second booking waits until the first has committed and then
finds what it made; the page answers once its booking is saved, and a booking that fails, by a problem
found or at the commit, is undone whole and said. `tools/install_pages.py` makes the lock node, a node
outside the model (label `MealPlannerBookingLock`, no Structr type), and a booking without it is
refused. `tools/check_bookings.py` sends bookings at once (the purchase four times, two recipes in one
week) and reads straight after each page answers; against the earlier pages it reports all three
problems. A booking by a signed-in user who is not the superuser (a test account, deleted afterwards)
was booked once, as the superuser, and shown on the page that answered. Not covered: a booking from the
terminal (`mealplanner/pantry.py` and the others write through REST, a request at a time) is not
serialized with one from a page. Not yet seen: a household member's own booking through a browser,
which needs their sign-in.

