"""Pin the USDA retention factors data/vocabulary.toml uses (mealplanner/usda_retention.py).

    python3 tools/retention_extract.py

Reads .cache/retention/retn06.txt (USDA Table of Nutrient Retention Factors, Release 6, from
ars.usda.gov; git-ignored) and writes data/retention/usda_r6.json: the rows the vocabulary's
retention classes name, with the nutrients its [retention] table lists, sorted, and the source
file's checksum, so a re-run changes nothing unless the vocabulary did. Commit the pinned file:
it is what tools/import_vocabulary.py reads. A row the table lacks is an error.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.usda_retention import pin
from mealplanner.vocabulary_import import VOCABULARY, VocabularyError, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, ".cache", "retention", "retn06.txt")
PINNED = "data/retention/usda_r6.json"


def main(argv=None) -> int:
    try:
        vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY), check_table=False)
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    if not vocabulary.retention:
        print("the vocabulary lists no retention nutrients: nothing to pin")
        return 1
    codes = {code for food in vocabulary.foods for _, code in food.retention}
    numbers = {number for _, number in vocabulary.retention.nutrients}
    try:
        pinned = pin(SOURCE, codes, numbers)
    except KeyError as exc:
        print(f"problem: {exc.args[0]}")
        return 1
    os.makedirs(os.path.join(ROOT, os.path.dirname(PINNED)), exist_ok=True)
    with open(os.path.join(ROOT, PINNED), "w") as fh:
        json.dump(pinned, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"{PINNED}: {len(pinned['rows'])} rows, {len(pinned['nutrients'])} nutrients")
    return 0


if __name__ == "__main__":
    sys.exit(main())
