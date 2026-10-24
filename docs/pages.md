# Pages: the week, the recipes, nutrition and the pantry in a browser

Structr serves four pages and a recipe page from the planner's own graph (the owner's choice,
2026-10-22: week view, recipe book, week's nutrition, pantry). They read; they never write.

| Page | Address | What it shows |
|---|---|---|
| Week | `/structr/html/week[/<MealPlan id>]` | a committed week's meals by day: cook or leftovers, servings cooked, each person's servings, and when to start a dish made ahead (J29) |
| Shopping | `/structr/html/shopping[/<MealPlan id>][?prices=<level>]` | a committed week's shopping list, as `tools/shopping_list.py` makes it: by the day each food is first needed, what to buy (a count where the recipes count it), what is on hand, the cost at a price level (default `Home prices`), what the pantry covers and what a recipe gives no amount for; a tick box on each line, remembered in that browser. Stock policies' levels are not applied here (the tool applies them; the page says so when one exists) |
| Recipes | `/structr/html/recipes[?meal=Breakfast]` | the book the planner chooses from (no baselines, nothing retired): meal types, minutes, difficulty, servings, and energy, protein, fibre and sodium a serving where targets are about them |
| Recipe | `/structr/html/recipe/<Plan id>` | one version: where it came from, its facts, its ingredients and amounts step by step, and every stored figure per serving with what it rests on. Instructions are not stored, so not shown |
| Nutrition | `/structr/html/nutrition[/<MealPlan id>]` | each of the week's targets judged at its own scope, per person: met, under, over or unknown, per day (and per meal or week where a target is scoped so) |
| Pantry | `/structr/html/pantry` | every portion on hand, how much, when it was weighed, and when it expires, soonest first |

A week page without an id shows the latest week with entries, and links the others. The week and
nutrition pages show **committed** weeks only: a proposed week exists nowhere until
`tools/plan_week.py --commit` writes it.

## How they are built

Each page is one server-side script: `pages/common.js`, then `pages/<name>.js`, run by Structr's
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
