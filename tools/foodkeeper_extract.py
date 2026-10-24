"""Pin the USDA FoodKeeper products data/vocabulary.toml names (mealplanner/foodkeeper.py).

    python3 tools/foodkeeper_extract.py

Reads .cache/foodkeeper/foodkeeper.json (USDA FSIS FoodKeeper data, from
fsis.usda.gov/shared/data/EN/foodkeeper.json; git-ignored. FSIS refuses scripted downloads, so save
it from a browser) and writes data/foodkeeper/foodkeeper.json: the products the foods name, with
their storage columns, sorted, and the source file's checksum and data version, so a re-run changes
nothing unless the vocabulary did. Commit the pinned file: it is what tools/import_vocabulary.py
reads. A product the file lacks is an error.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.foodkeeper import pin
from mealplanner.vocabulary_import import VOCABULARY, VocabularyError, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, ".cache", "foodkeeper", "foodkeeper.json")
PINNED = "data/foodkeeper/foodkeeper.json"


def main(argv=None) -> int:
    try:
        vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY), check_subset=False)
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    ids = {food.keeps[0] for food in vocabulary.foods if food.keeps}
    try:
        pinned = pin(SOURCE, ids)
    except KeyError as exc:
        print(f"problem: {exc.args[0]}")
        return 1
    os.makedirs(os.path.join(ROOT, os.path.dirname(PINNED)), exist_ok=True)
    with open(os.path.join(ROOT, PINNED), "w") as fh:
        json.dump(pinned, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"{PINNED}: {len(pinned['products'])} products, FoodKeeper data version {pinned['version']:g} "
          f"({pinned['modified']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
