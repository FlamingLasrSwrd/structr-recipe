# Recipe files

A recipe is transcribed into one TOML file and loaded with `tools/import_recipe.py`
(`mealplanner/recipe_import.py`). The file is the reviewable record of the transcription; the
recipe itself lives in Structr. Real recipe files belong in `private/recipes/`, which git ignores:
the repository is public, the owner's data is not.

```bash
bash tools/owner_stack.sh up                       # the owner's instance, on port 8085
set -a && source .env && set +a
export STRUCTR_URL=http://localhost:8085
python3 tools/import_recipe.py --check private/recipes/*.toml   # parse and look up every name; write nothing
python3 tools/import_recipe.py private/recipes/*.toml           # load
```

## An example

```toml
name = "Garlic Butter Noodles"            # the RecipeIdentity, and by default the dish
source = "https://example.org/noodles"    # optional: the page it was transcribed from
servings = 4                              # what the recipe yields, in servings
minutes = 25                              # optional: total time, the time spent working
# ahead_hours = 8                         # optional: hours it must be started before the meal, for waiting
                                          # no one attends (oats soaking overnight); see "Made ahead"
difficulty = "easy"                       # optional: easy, medium or hard
meal_types = ["Dinner", "Lunch"]          # at least one, from the Meal Type scheme
# version = 2                             # optional, default 1: see "Changing a recipe"
# dish = "Noodle Bowl"                    # optional: the dish's food type, if not the name

[[steps]]
name = "boil the noodles"                 # optional label, default "step N"
method = "Boiling"                        # optional: a Transformation Method
makes = "Noodles (cooked)"                # every step but the last names what it makes
inputs = [{ food = "Noodles (dry)", amount = 400, unit = "g" }]

[[steps]]                                 # the last step makes the dish
name = "toss"
equipment = ["Wok"]                       # optional: the tools the step needs
inputs = [
  { food = "Noodles (cooked)" },          # made by the step above: no amount needed
  { food = "Butter", amount = 3, unit = "tbsp" },
  { food = "Garlic", amount = 4, unit = "each" },
  { food = "Salt" },                      # "to taste": no amount
  { food = "Parsley", amount = 5, unit = "g", optional = true },
]
```

## Rules

- **Every ingredient, method and meal type must already be in the vocabulary**, under those exact
  names. A name that does not resolve stops the file before anything is written, and every such
  name is listed, so a typo never becomes a new food. The dish and anything a step `makes` are
  food types too: an existing one is reused, a new one is created.
- **Units** are `g`, `kg`, `mg`, `oz`, `lb`, `ml`, `l`, `cup`, `tbsp`, `tsp`, `fl_oz`, `dash`
  (1/8 tsp), `pinch` (1/16 tsp), `each`, `whole` and `count`. A volume or a count converts to grams only if the food has a `Density` or
  `MassPerUnit` default; the loader names any quantity that does not, since that ingredient's
  nutrition stays unknown until it does.
- **Equipment** names must be in the vocabulary too (the Equipment Type hierarchy); choose them from
  `python3 tools/instantiate_profile.py kitchen --list`. Name the most general tool that will do
  (`Skillet`, not `Nonstick skillet`, unless the recipe needs nonstick): any subtype meets the need.
  Each becomes an instrument-role Specification of its Step: the model's place for a tool a process
  needs, with no quantity. Where any of several tools will do, name what they do instead (below, "A
  tool named by what it does").
- **One dish per recipe.** Every step but the last must make something a later step uses, and
  nothing may be used before it is made.
- **Names** cannot contain a comma or a semicolon (Structr's exact-match lookup cannot find them).

## The basic recipe set

`data/recipes/` holds 20 recipes that ship with the repository (2026-10-31, at the owner's request: "a
basic set along with the git project"), so a new instance has something to plan with. They are
transcribed, facts only and by the rules above, from three NIH NHLBI recipe books, which are US
government works and in the public domain: *Keep the Beat Recipes: Deliciously Healthy Dinners*
(NIH 10-2921), *Deliciously Healthy Family Meals* (NIH 10-7531) and *Heart-Healthy Home Cooking African
American Style* (NIH 21-HL-3792). Each file names its book in `source` and its page and choices in a
comment. The books' photographs, by a private studio, are not used, as no photograph is.

Chosen as a representative mix: 5 breakfasts, 5 lunches, 8 dinners and 2 snacks; poultry, fish, beef,
pork, beans and lentils, eggs and tofu, ten of them with no meat or fish; baking, simmering,
stir-frying, broiling, roasting and no cooking at all; from a 5-minute smoothie to a 50-minute
stir-fry; and a few that need less common tools (a waffle iron, a blender or food processor, skewers),
so the importer's kitchen check has something to ask about. `tests/test_basic_recipes.py` checks that
each still loads and names only what the vocabulary holds, and that the mix stays as chosen.

Each file's header gives the energy per serving its book prints, an independent check of the
transcription and of the vocabulary's matches. Loaded on the development instance (2026-10-31), every
recipe's energy is known and the median recipe is 17% from its book, 8 of the 20 within 15%; the
furthest are the pork chops (+106%: FDC's only chop is 170 g of lean and fat, the book's are half-inch
lean ones), the salmon (+39%) and the tofu stir-fry (+30%). The books' own figures are estimates from
other data, so a difference is a question about the match, not a verdict on it.

They are loaded only when asked for, never by the build, and not into the owner's instance unless the
owner does it (some may be near recipes already there). Not on a stack the demos are run on either:
`scripts/26a`'s planner checks assume that every recipe but its own fixtures lacks usable nutrition,
and these have it (`docs/todo.md`).

```bash
python3 tools/import_recipe.py --check data/recipes/*.toml   # needs the vocabulary imported first
python3 tools/import_recipe.py data/recipes/*.toml
```

## A daily baseline

What is eaten every day outside the planned meals (supplements, the morning coffee) is written as a
recipe with `baseline = true` and no `meal_types`, one serving being one day of it (`servings = 1`).
It is never offered as a meal; a week counts it every day once it is named in the week file
(`tools/plan_week.py`, `baseline = [...]`). The owner's is `private/baseline.toml`:

```toml
name = "Daily supplements"
baseline = true
servings = 1

[[steps]]
name = "take the supplements"
inputs = [{ food = "Vitamin D3 supplement (1000 IU)", amount = 1, unit = "each" }]
```

A supplement is a `label` food in the vocabulary: its figures per unit, as its label states them,
and every other nutrient none. It is counted with `each`.

## Made ahead

A dish that must wait hours before it is eaten, with no one attending it (overnight oats soaking,
a dough rising, a long marinade), states the wait apart from its working time (data-model.md J29):

```toml
name = "Overnight Oats"
minutes = 5                               # the time spent making it
ahead_hours = 8                           # then 8 hours in the fridge
```

`minutes` is what the time budget scores, so the 5 minutes count, not the night. The planner does
not plan the dish for a meal less than `ahead_hours` after the plan is made, and the week it
proposes says when to start it ("made ahead: start it by Sun 23:00"). Making several servings at
once and eating them on later days is ordinary leftovers, within their keeping time.

## Transcribing a recipe

Only facts are transcribed: ingredients, amounts, servings, times and the order of operations.
A page's own instructions are not copied; its address goes in `source`. What may be kept and what
may not, with the law behind it, is in `docs/recipe-copyright.md`; a step's name is a label of at
most 80 characters. Choices a transcription
makes go in a comment at the top of the file. The conventions so far (`docs/data-model.md` §18 J20):

- **A seasoning "to taste"** is `optional`, with no amount. An ingredient with no amount would make
  every figure it contributes to unknown.
- **A size** ("1 large onion") is written in grams from FDC's portion for that size, since a food
  has one weight per item.
- **An ingredient split across steps** ("1 tbsp, divided") is split between the steps; say how if
  the page does not.
- **A discarded marinade** is counted as eaten, and the file says so: the model cannot yet say an
  output is thrown away.
- **An ingredient with no known weight for its measure** keeps the recipe's unit; the loader names
  it. Find a weight (another USDA dataset, a brand's label, the web) and add it to the vocabulary
  with its source, `estimated` if it is not a published figure for that food.
- **A size stated as a can or a package** ("3 cans of beans, drained") is written as `each` of a
  food whose weight per item is that can's (drained) weight, with its source.
- **A side "for serving"** with no amount is `optional`.
- **An amount the page sends but does not use** ("we sent more", "use the rest as you like") is not
  counted: the file takes what the steps use. An amount "to taste" or "as much as you like" that the
  page does list is counted.
- **Pantry items a meal kit leaves to the cook** ("a drizzle of oil") are split over the steps from the
  page's total; where it gives no total, a drizzle is 1 tsp and a large drizzle 2 tsp, an estimate.
- **A kit's "unit"** (a packet of jam, a container of corn) is written in grams or a household measure,
  with the estimate in the file's comment, unless the vocabulary gives the food a weight per item.
- Every food must be in `data/vocabulary.toml`, matched to a USDA food (`tools/import_vocabulary.py`).

## A step's facts

Each optional, each a fact (`docs/recipe-copyright.md`), each where the model already keeps such
things (`docs/data-model.md` §18 J35):

```toml
[[steps]]
name = "roast the chicken"
method = "Roasting"
makes = "Chicken (roasted)"
after = []                                # the steps before it, by name; default: the one before it.
                                          # [] starts it at once, beside the others
minutes = 5                               # working time: it takes someone's attention
wait_minutes = 25                         # waiting time: it then needs no one (roasting, simmering, resting)
until = "golden"                          # doneness in a few words (at most 60 characters)
inside = { temp = 165, unit = "F" }       # the temperature the food reaches inside (USDA FSIS's minimums)
equipment = [{ tool = "Oven", temp = 425, unit = "F" }]    # a tool set to a temperature, F or C,
                                          # or { tool = "Skillet", heat = "medium-high" }: low, medium-low,
                                          # medium, medium-high or high; or just its name, as before
inputs = [{ food = "Chicken", amount = 300, unit = "g" }]
```

- **Order.** A step that uses what another makes must come after it, directly or through the steps
  between; the loader says so if `after` would put it earlier. Two steps neither of which comes
  before the other may be done side by side.
- **Times.** `minutes` and `wait_minutes` are the step's own. The recipe's `minutes` stays its total
  working time, which the planner scores; nothing adds the steps' up for it.
- **Cut forms** are methods: `Chopping`, `Dicing`, `Mincing`, `Slicing`, `Grating`, `Peeling` and
  `Mashing`, under `Mechanical Method` in `data/vocabulary.toml`. They apply no heat, so every nutrient
  is kept whole. A cut that matters downstream names what it makes (`makes = "Onion (diced)"`).
- **Heat and doneness** need the Quality Kinds `Temperature`, `Heat Level` and `Doneness`, which
  `scripts/41a` makes; the loader names a missing one before writing anything.
- **A recipe already cooked** is history: adding facts to its file is a change, so it loads as a new
  `version`.

## What may stand in

An ingredient may say what can take its place (`docs/data-model.md` §5.3, §18 J36):

```toml
inputs = [
  { food = "Butter", amount = 3, unit = "tbsp", substitutes = [
      { food = "Olive oil", ratio = 0.75 },   # 0.75 tbsp of oil for each tbsp of butter
      { food = "Canola oil", ratio = 0.75 },
      { food = "Peanut oil", never = true },  # never, however alike it seems
  ] },
  { food = "Lime", amount = 1, unit = "each", substitutes = [{ food = "Lemon" }] },   # ratio 1: as much
]
```

- **A substitute is a food in the vocabulary**, as the ingredient is, and the loader names one that is
  not. `ratio` (default 1) is how much of it for one of the ingredient, in the ingredient's unit.
- **`never`** rules a food out. The model's rule is that an authored rule decides and a computed
  similarity only suggests (§5.3); nothing computes suggestions yet, so for now `never` keeps a food
  off the page and out of any later suggestion.
- **Not for something an earlier step made** (give that step's ingredients their substitutes
  instead), not the food itself, and not one food twice.
- **Only the page reads them, for now.** The nutrition, the shopping list, the pantry and the planner
  count the ingredient the recipe names; a cook that used the olive oil because the butter ran out
  has no way to say so yet (invariant 18's `via_substitution`, not built).

## A tool named by what it does

Where a recipe does not care which tool ("broil or grill", "an oven or a toaster oven"), a step names a
capability instead of a tool (`docs/data-model.md` §18 J37):

```toml
equipment = ["Sheet pan", { capability = "Broiler heat", heat = "high" }]   # set as a tool is: temp and unit, or heat
```

- **A capability is in the vocabulary**, under `Capability` in `data/vocabulary.toml`: for now `Heating`,
  and under it `Oven heat` and `Broiler heat`, and `Puréeing`. Each tool's type says what it `can` give
  (an `Oven` gives oven heat and broiler heat, a `Grill` broiler heat, a `Food processor` purées), and the loader names a capability
  that is not one, or a tool named as one.
- **Any tool that can give it will do**, or give one of its subtypes: `Heating` is met by an oven, a
  toaster oven or a grill. The step's sentence names them: "on the grill or oven over high heat".
- **The importer checks the kitchen** (since 2026-10-31, the owner's decision: at import, not when a week
  is planned). Every kitchen on the instance (a `UtensilSet`, `tools/instantiate_profile.py kitchen`) is
  compared with the steps' tools: a tool is met by one of that type or a narrower one, a capability by a
  tool whose type, or a type above it, gives it or a narrower one (`mealplanner/kitchen_check.py`). What
  a kitchen lacks is listed, and the importer asks "Import it anyway? [y/N]" before loading such a
  recipe; run with no one to answer (not in a terminal), it skips that recipe, says so, and exits 1.
  `--check` lists what is missing and asks nothing, and so does a recipe already loaded unchanged, so
  running `--check` over the files checks them against a changed kitchen. The planner does not read a
  step's tools.

## Instructions written from the steps

The recipe page's **How to make it** writes each step as one sentence of our own from its facts, by
fixed rules (`mealplanner/instructions.py`; `pages/lib/75_instructions.js` writes the same, word for
word): the method's verb (or, with no method, the step's label), the ingredients with their amounts
("the" for what an earlier step made) and what may stand in, scaled by its ratio ("3 tbsp butter (or
2.25 tbsp olive oil, or 2.25 tbsp canola oil)", the peanut oil left out), the tools with their heat (a
capability as the tools that can give it, "in the oven or toaster oven at 350 °F", or "with the food
processor, high-speed blender or immersion blender" where it is set to nothing), the doneness, the time, and "Meanwhile" for a step
that does not follow the one before. A recipe of four steps, the third the one in "A step's facts"
above, reads:

1. Rinse the rice: 150 g rice, about 2 minutes.
2. Simmer the rice (rinsed) on the stove over low heat using the saucepan, about 20 minutes, 2 of them hands-on.
3. Meanwhile, roast 300 g chicken in the oven at 425 °F until golden and 165 °F inside, about 30 minutes, 5 of them hands-on.
4. Serve: the rice (cooked) and the chicken (roasted).

So a step's label is best a few words of what it does ("rinse the rice"), and facts left out are left
out of the sentence: nothing is guessed.

## What it becomes

A `RecipeIdentity` (meal types; an `Identifier` for the source page), a `Plan` named
`<name> v<version>` (yield in servings, minutes, difficulty, hours made ahead), and for each step a `Step` (its
transformation method) with one input `Specification` per ingredient, an output `Specification`
for what it makes, and an instrument `Specification` per piece of equipment. A step's minutes are
QuantitySpecifications, its order is `isPrecededBy`, and a tool's heat or a product's doneness is a
`StateRequirement` on its Specification (J35). A capability is an instrument Specification that specifies it
(J37), and each substitute is a `SubstitutionRule` on its
ingredient's Specification, naming the food, its ratio and whether it is ruled out (J36). The page's prose is not stored: a Step records what goes in, what comes out, how and with what, in order. An actual
cook is a separate thing, a `Process` that concretizes the Plan with the quantities really used
(`scripts/15c` shows one); there is no tool to record a cook yet. The dish's
mass is not stored: nutrition per serving is worked out from the ingredients
(`docs/data-model.md` §18 J18).

## Changing a recipe

Loading a file twice changes nothing. An edited file updates the same Plan, and Steps and
ingredients it no longer lists are deleted. Once a Plan has been cooked it is history (a cook's
Allocations point at its Specifications), so a changed file for it is refused: give the file a
new `version` and it loads as a second Plan of the same recipe.
