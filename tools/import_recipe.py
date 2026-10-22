"""Load recipe files into Structr (mealplanner/recipe_import.py, docs/recipe-format.md).

    python3 tools/import_recipe.py private/recipes/*.toml          # load
    python3 tools/import_recipe.py --check private/recipes/*.toml  # parse and resolve names; write nothing

Each file is checked in full before anything is written: every problem in it
is listed, and a name that is not in the vocabulary stops that file. A file
already loaded changes nothing. Exits 1 if any file failed. Each recipe loaded
then has its nutrition per serving worked out again and stored, where the
instance can store it (mealplanner/recipe_nutrition.py, J28).

Needs STRUCTR_SUPERUSER_PASSWORD (and optionally STRUCTR_URL) in the
environment: `set -a && source .env && set +a`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.recipe_import import (
    RecipeFormatError, RecipeFrozenError, RecipeResolutionError, import_recipe, read_recipe,
)
from mealplanner.recipe_nutrition import calculate, schema_ready


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--check", action="store_true", help="parse and resolve names only; write nothing")
    args = parser.parse_args(argv)

    client = connect(owner_data_ok=True)        # this tool is how the owner's recipes get in
    client.wait_until_ready()
    failed = 0
    loaded = []
    for path in args.files:
        print(f"== {path}")
        try:
            doc = read_recipe(path)
            result = import_recipe(client, doc, check_only=args.check)
        except (RecipeFormatError, RecipeResolutionError) as exc:
            failed += 1
            for problem in exc.problems:
                print(f"   problem: {problem}")
            continue
        except (RecipeFrozenError, OSError, ValueError) as exc:
            failed += 1
            print(f"   problem: {exc}")
            continue
        if args.check:
            print(f"   ok: {doc.plan_name}, {len(result.foods)} ingredients, "
                  f"{sum(1 for v in result.products.values() if v is None)} new product type(s)")
            continue
        print(f"   {'unchanged' if result.plan_unchanged else 'loaded'}: {doc.plan_name}")
        loaded.append(result.plan_id)
        for name in result.created_types:
            print(f"   new food type: {name}")
        for name in result.removed:
            print(f"   removed: {name}")
        for text in result.unconvertible:
            print(f"   no conversion to grams (nutrition unknown until the food has a Density or MassPerUnit): {text}")
        for food in result.without_profiles:
            print(f"   no nutrient profile yet: {food}")
    if loaded and schema_ready(client):
        # their nutrition per serving, stored for the planner (J28): worked out again, kept if unchanged
        report = calculate(client, loaded)
        print("recipe nutrition per serving: " + ", ".join(f"{k} {v}" for k, v in report.counts.items()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
