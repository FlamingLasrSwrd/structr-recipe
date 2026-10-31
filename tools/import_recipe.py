"""Load recipe files into Structr (mealplanner/recipe_import.py, docs/recipe-format.md).

    python3 tools/import_recipe.py private/recipes/*.toml          # load
    python3 tools/import_recipe.py --check private/recipes/*.toml  # parse and resolve names; write nothing

Each file is checked in full before anything is written: every problem in it
is listed, and a name that is not in the vocabulary stops that file. A file
already loaded changes nothing. Exits 1 if any file failed. Each recipe loaded
then has its nutrition per serving worked out again and stored, where the
instance can store it (mealplanner/recipe_nutrition.py, J28).

The steps' tools are checked against every kitchen on the instance
(mealplanner/kitchen_check.py; the owner's decision of 2026-10-31: at import,
not when a week is planned). What a kitchen lacks is listed, and before a recipe
that needs it is loaded the tool asks "Import it anyway?". With no one to answer
(not run in a terminal) that recipe is skipped and reported, and the run exits 1.
--check lists what is missing and asks nothing; so does a recipe already loaded
unchanged, which is how a changed kitchen is checked against the recipes again.

Needs STRUCTR_TOOLS_PASSWORD (and optionally STRUCTR_URL) in the
environment: `set -a && source .env && set +a`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import kitchen_check
from mealplanner.connection import connect
from mealplanner.recipe_import import (
    RecipeFormatError, RecipeFrozenError, RecipeResolutionError, import_recipe, loaded_unchanged, read_recipe,
)
from mealplanner.recipe_nutrition import calculate, schema_ready

YES = {"y", "yes"}


def tools_missing(client, doc, names, kitchens) -> bool:
    """Print what each kitchen lacks for `doc`'s steps; whether any kitchen lacks something."""
    lacking = False
    for kitchen in kitchens:
        gaps = kitchen_check.missing(client, doc.steps, names.equipment, kitchen)
        if gaps:
            lacking = True
            print(f"   missing in the kitchen {kitchen['name']!r}: " + "; ".join(kitchen_check.describe(g) for g in gaps))
    return lacking


def main(argv=None, ask=input, interactive=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--check", action="store_true", help="parse and resolve names only; write nothing")
    args = parser.parse_args(argv)
    if interactive is None:
        interactive = sys.stdin.isatty()

    client = connect(owner_data_ok=True)        # this tool is how the owner's recipes get in
    client.wait_until_ready()
    kitchens = kitchen_check.kitchens(client)
    if not kitchens:
        print("no kitchen on this instance (tools/instantiate_profile.py kitchen): the steps' tools are not checked")
    failed = 0
    loaded = []
    for path in args.files:
        print(f"== {path}")
        try:
            doc = read_recipe(path)
            names = import_recipe(client, doc, check_only=True)
            lacking = tools_missing(client, doc, names, kitchens)
            if lacking and not args.check and not loaded_unchanged(client, doc):
                if not interactive:
                    failed += 1
                    print("   skipped: the kitchen lacks what it needs, and no one is here to ask; "
                          "run this in a terminal to answer, or add the tool to the kitchen")
                    continue
                if ask("   Import it anyway? [y/N] ").strip().lower() not in YES:
                    print("   not imported")
                    continue
            result = names if args.check else import_recipe(client, doc)
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
