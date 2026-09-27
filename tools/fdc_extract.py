"""Pin the FoodData Central foods data/vocabulary.toml names (mealplanner/fdc.py).

    python3 tools/fdc_extract.py .cache/fdc/FoodData_Central_sr_legacy_food_csv_2018-04.zip

Reads the zip (download it from fdc.nal.usda.gov/download-datasets into the
git-ignored .cache/fdc/), extracts every food the vocabulary maps to, and writes
data/fdc/sr_legacy.json, sorted so a re-run changes nothing unless the
vocabulary did. Commit that file: it is what tools/import_vocabulary.py reads.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.fdc import extract
from mealplanner.vocabulary_import import VOCABULARY, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY), check_subset=False)
    ids = {f.fdc for f in vocabulary.foods if f.fdc} | {f.density_from for f in vocabulary.foods if f.density_from}
    subset = extract(args[0], ids)
    out = os.path.join(ROOT, vocabulary.subset)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(subset, fh, indent=1, sort_keys=False, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {vocabulary.subset}: {len(subset['foods'])} foods, {len(subset['nutrients'])} nutrients")
    return 0


if __name__ == "__main__":
    sys.exit(main())
