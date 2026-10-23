"""Load data/vocabulary.toml into Structr (mealplanner/vocabulary_import.py).

    python3 tools/import_vocabulary.py            # load
    python3 tools/import_vocabulary.py --check    # validate the file against the pinned FDC subset; write nothing

Idempotent: a second run changes nothing. When a run changes a food's profiles, density,
weight per item, retention factors or place in the hierarchy, the stored nutrition per serving
of every recipe using it, or a food below it, is worked out again (J28). --check also lists every food that lacks a
Nutrition Facts figure (vocabulary_import.CORE_NUTRIENTS). Meant for the owner's instance as well
as any other; needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.recipe_nutrition import calculate, plans_using, schema_ready
from mealplanner.vocabulary_import import VOCABULARY, VocabularyError, core_gaps, import_vocabulary, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    try:
        vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY))
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(f"{VOCABULARY}: {len(vocabulary.foods)} foods, {len(vocabulary.methods)} methods, "
          f"{len(vocabulary.equipment)} equipment, {len(vocabulary.fdc['nutrients'])} FDC nutrients")
    for food in vocabulary.foods:
        gaps = core_gaps(vocabulary.fdc, food) if food.sources else []
        if gaps:
            print(f"gap: {food.name} has no {', '.join(gaps)}: add a source that reports it")
    if args.check:
        return 0
    client = connect(owner_data_ok=True)      # the vocabulary goes into the owner's instance too
    client.wait_until_ready()
    try:
        imported = import_vocabulary(client, vocabulary)
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in imported.counts.items()))
    if imported.affected and schema_ready(client):
        # what a recipe's stored nutrition per serving rests on changed for these foods: the
        # recipes using them, or a food below them, are worked out again (J28)
        plan_ids = plans_using(client, imported.affected)
        if not plan_ids:
            print(f"recipe nutrition per serving: no recipe uses the {len(imported.affected)} changed food(s)")
            return 0
        report = calculate(client, plan_ids)
        print(f"recipe nutrition per serving, {report.plans} recipe(s) using the {len(imported.affected)} changed "
              f"food(s): " + ", ".join(f"{k} {v}" for k, v in report.counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
