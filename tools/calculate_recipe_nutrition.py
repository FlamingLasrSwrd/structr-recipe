"""Work out each recipe's nutrition per serving and store it (mealplanner/recipe_nutrition.py, J28).

    python3 tools/calculate_recipe_nutrition.py                    # every recipe
    python3 tools/calculate_recipe_nutrition.py "Pad Thai v1"      # these Plans, by name
    python3 tools/calculate_recipe_nutrition.py --check            # store nothing; list stored figures that differ

The planner reads the stored figures. tools/import_recipe.py and tools/import_vocabulary.py
run this for what they change; run it by hand after changing anything else a figure rests
on. Needs scripts/35a. Exits 1 if --check found a difference or a name is not a Plan.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.recipe_nutrition import calculate, schema_ready


def describe(report) -> str:
    return f"recipe nutrition per serving, {report.plans} recipe(s): " + ", ".join(f"{k} {v}" for k, v in report.counts.items())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plans", nargs="*", help="Plan names, e.g. \"Pad Thai v1\"; every Plan if none")
    parser.add_argument("--check", action="store_true", help="store nothing; list stored figures that differ")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)        # the owner's recipes are what it is for
    client.wait_until_ready()
    if not schema_ready(client):
        print("problem: this instance cannot store them yet: run scripts/35a_recipe_nutrition_schema.py")
        return 1
    ids = None
    if args.plans:
        ids, missing = [], []
        for name in args.plans:
            found = client.get("/structr/rest/Plan", params={"name": name})["result"]
            (ids.append(found[0]["id"]) if len(found) == 1 else missing.append(name))
        if missing:
            print(f"problem: no single Plan named {', '.join(repr(m) for m in missing)}")
            return 1
    report = calculate(client, ids, check=args.check)
    if args.check:
        for text in report.differences:
            print(f"differs: {text}")
        print(f"checked {report.plans} recipe(s): {len(report.differences)} difference(s)")
        return 1 if report.differences else 0
    print(describe(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
