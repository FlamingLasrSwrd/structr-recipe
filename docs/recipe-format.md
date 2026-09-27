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
minutes = 25                              # optional: total time
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
- **Equipment** names must be in the vocabulary too (the Equipment Type hierarchy). Each becomes an
  instrument-role Specification of its Step: the model's place for a tool a process needs, with no
  quantity.
- **One dish per recipe.** Every step but the last must make something a later step uses, and
  nothing may be used before it is made.
- **Names** cannot contain a comma or a semicolon (Structr's exact-match lookup cannot find them).

## Transcribing a recipe

Only facts are transcribed: ingredients, amounts, servings, times and the order of operations.
A page's own instructions are not copied; its address goes in `source`. Choices a transcription
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
- Every food must be in `data/vocabulary.toml`, matched to a USDA food (`tools/import_vocabulary.py`).

## What it becomes

A `RecipeIdentity` (meal types; an `Identifier` for the source page), a `Plan` named
`<name> v<version>` (yield in servings, minutes, difficulty), and for each step a `Step` (its
transformation method) with one input `Specification` per ingredient, an output `Specification`
for what it makes, and an instrument `Specification` per piece of equipment. The page's prose is
not stored: a Step records what goes in, what comes out, how and with what, in order. An actual
cook is a separate thing, a `Process` that concretizes the Plan with the quantities really used
(`scripts/15c` shows one); there is no tool to record a cook yet. The dish's
mass is not stored: nutrition per serving is worked out from the ingredients
(`docs/data-model.md` §18 J18).

## Changing a recipe

Loading a file twice changes nothing. An edited file updates the same Plan, and Steps and
ingredients it no longer lists are deleted. Once a Plan has been cooked it is history (a cook's
Allocations point at its Specifications), so a changed file for it is refused: give the file a
new `version` and it loads as a second Plan of the same recipe.
