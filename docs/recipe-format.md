# Recipe files

A recipe is transcribed into one TOML file and loaded with `tools/import_recipe.py`
(`mealplanner/recipe_import.py`). The file is the reviewable record of the transcription; the
recipe itself lives in Structr. Real recipe files belong in `private/recipes/`, which git ignores:
the repository is public, the owner's data is not.

```bash
set -a && source .env && set +a
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
- **Units** are `g`, `kg`, `mg`, `oz`, `lb`, `ml`, `l`, `cup`, `tbsp`, `tsp`, `fl_oz`, `each`,
  `whole` and `count`. A volume or a count converts to grams only if the food has a `Density` or
  `MassPerUnit` default; the loader names any quantity that does not, since that ingredient's
  nutrition stays unknown until it does.
- **One dish per recipe.** Every step but the last must make something a later step uses, and
  nothing may be used before it is made.
- **Names** cannot contain a comma or a semicolon (Structr's exact-match lookup cannot find them).

## What it becomes

A `RecipeIdentity` (meal types; an `Identifier` for the source page), a `Plan` named
`<name> v<version>` (yield in servings, minutes, difficulty), and for each step a `Step` with one
input `Specification` per ingredient and an output `Specification` for what it makes. The dish's
mass is not stored: nutrition per serving is worked out from the ingredients
(`docs/data-model.md` §18 J18).

## Changing a recipe

Loading a file twice changes nothing. An edited file updates the same Plan, and Steps and
ingredients it no longer lists are deleted. Once a Plan has been cooked it is history (a cook's
Allocations point at its Specifications), so a changed file for it is refused: give the file a
new `version` and it loads as a second Plan of the same recipe.
