"""Pin the FoodData Central foods data/vocabulary.toml refers to (mealplanner/fdc.py).

    python3 tools/fdc_extract.py                     # pin from the datasets in .cache/fdc/
    python3 tools/fdc_extract.py --search "palm sugar" [--search ...]
                                                     # save FDC API branded search results first

Reads whichever of these are in the git-ignored .cache/fdc/ (download them from
fdc.nal.usda.gov/download-datasets):

  FoodData_Central_sr_legacy_food_csv_2018-04.zip         -> data/fdc/sr_legacy.json
  FoodData_Central_foundation_food_csv_2025-12-18.zip     -> data/fdc/foundation.json
  FoodData_Central_survey_food_json_2024-10-31.zip        -> data/fdc/fndds.json
  api/<query>.json (saved branded search results)         -> data/fdc/branded.json

and writes, for each, the foods the vocabulary names that it holds, sorted, so a
re-run changes nothing unless the vocabulary did. Commit the data/fdc files:
they are what tools/import_vocabulary.py reads. An id found in none is an error.

--search asks the FDC API (key FDC_API_KEY, else DEMO_KEY: 10 requests an hour)
for branded foods matching a query and saves the result under .cache/fdc/api/,
so a label can be chosen and pinned without the 427 MB branded download.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.fdc import extract, extract_branded, extract_survey
from mealplanner.vocabulary_import import VOCABULARY, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "fdc")
DATASETS = [   # (source in the cache, reader, pinned file)
    ("FoodData_Central_sr_legacy_food_csv_2018-04.zip", extract, "data/fdc/sr_legacy.json"),
    ("FoodData_Central_foundation_food_csv_2025-12-18.zip", extract, "data/fdc/foundation.json"),
    ("FoodData_Central_survey_food_json_2024-10-31.zip", extract_survey, "data/fdc/fndds.json"),
    ("api", extract_branded, "data/fdc/branded.json"),
]
API = "https://api.nal.usda.gov/fdc/v1/foods/search"


def search(query: str) -> str:
    params = urllib.parse.urlencode({"api_key": os.environ.get("FDC_API_KEY", "DEMO_KEY"), "query": query,
                                     "dataType": "Branded", "pageSize": 40})
    with urllib.request.urlopen(f"{API}?{params}", timeout=60) as response:
        body = json.load(response)
    os.makedirs(os.path.join(CACHE, "api"), exist_ok=True)
    path = os.path.join(CACHE, "api", f"{query}.json")
    with open(path, "w") as fh:
        json.dump(body, fh)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--search", action="append", default=[], help="save FDC API branded search results")
    args = parser.parse_args(argv)
    for query in args.search:
        print(f"saved {search(query)}")
    if args.search:
        return 0

    vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY), check_subset=False)
    wanted = vocabulary.ids()
    found: set[int] = set()
    for source, reader, pinned in DATASETS:
        path = os.path.join(CACHE, source)
        if not os.path.exists(path):
            continue
        subset = reader(path, wanted - found, strict=False)
        if not subset["foods"]:
            continue
        found |= {int(i) for i in subset["foods"]}
        with open(os.path.join(ROOT, pinned), "w") as fh:
            json.dump(subset, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print(f"wrote {pinned}: {len(subset['foods'])} foods, {len(subset['nutrients'])} nutrients")
    missing = sorted(wanted - found)
    if missing:
        print(f"problem: no dataset in {CACHE} holds FDC {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
