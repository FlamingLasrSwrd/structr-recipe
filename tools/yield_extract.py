"""Pin USDA SR28's refuse for the foods data/vocabulary.toml trims (mealplanner/yields.py, J41).

    python3 tools/yield_extract.py [--fetch]

Reads SR28's FOOD_DES.txt from .cache/sr28/sr28asc.zip (ars.usda.gov, public domain; git-ignored;
--fetch downloads it first) and FDC's sr_legacy_food.csv from .cache/fdc/FoodData_Central_sr_legacy_
food_csv_2018-04.zip (tools/fdc_extract.py's input), which maps an FDC id to its NDB number, and
writes data/yields/sr28.json: for each food with a `trim` whose FDC record is an SR Legacy food, its
NDB number, description, refuse (percent of the food as purchased) and what the refuse is. Commit it:
tools/import_vocabulary.py reads it, and a pinned figure replaces the trim's estimate, `sourced`.
Prints each food's estimate beside SR28's, for review. A re-run changes nothing unless the
vocabulary or the files did.
"""

import argparse
import json
import os
import sys
import tomllib
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.vocabulary_import import VOCABULARY, VocabularyError, read_vocabulary
from mealplanner.yields import SR28_PIN, SR28_URL, SR_LEGACY_ZIP, ndb_numbers, parse_food_des, sr28_pin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR28_ZIP = os.path.join(ROOT, ".cache", "sr28", "sr28asc.zip")
FDC_ZIP = os.path.join(ROOT, ".cache", "fdc", SR_LEGACY_ZIP)


def member(path: str, name: str) -> str:
    """The text of the member of a zip whose file name is `name`, wherever it sits in the archive."""
    with zipfile.ZipFile(path) as archive:
        (inner,) = [n for n in archive.namelist() if os.path.basename(n).lower() == name.lower()]
        return archive.read(inner).decode("latin-1" if name.endswith(".txt") else "utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true", help=f"download {SR28_URL} first")
    args = parser.parse_args(argv)
    if args.fetch:
        os.makedirs(os.path.dirname(SR28_ZIP), exist_ok=True)
        urllib.request.urlretrieve(SR28_URL, SR28_ZIP)
    for path in (SR28_ZIP, FDC_ZIP):
        if not os.path.exists(path):
            print(f"problem: {os.path.relpath(path, ROOT)} is missing" + (" (--fetch downloads it)" if path == SR28_ZIP else
                                                                          " (tools/fdc_extract.py's input, from fdc.nal.usda.gov)"))
            return 1
    try:
        vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY))
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    with open(os.path.join(ROOT, VOCABULARY), "rb") as fh:      # the file's own: a food the pin says has no refuse has no Trim
        estimates = {f["name"]: f["trim"]["refuse"] for f in tomllib.load(fh)["food"] if "trim" in f}
    trimmed = {f.name: f.fdc for f in vocabulary.foods if f.name in estimates and f.fdc
               and vocabulary.fdc["foods"].get(str(f.fdc), {}).get("data_type") == "sr_legacy_food"}
    pinned = sr28_pin(parse_food_des(member(SR28_ZIP, "FOOD_DES.txt")), ndb_numbers(member(FDC_ZIP, "sr_legacy_food.csv")),
                      trimmed.values())
    os.makedirs(os.path.join(ROOT, os.path.dirname(SR28_PIN)), exist_ok=True)
    with open(os.path.join(ROOT, SR28_PIN), "w") as fh:
        json.dump(pinned, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    for name, fid in sorted(trimmed.items()):
        row = pinned["foods"].get(str(fid))
        sr28 = f"{row['refuse']:g}% ({row['what']})" if row else "not in SR28"
        print(f"  {name:<20} estimated {estimates[name]:g}%, SR28 {sr28}")
    print(f"{SR28_PIN}: {len(pinned['foods'])} of {len(trimmed)} trimmed SR foods; run tools/import_vocabulary.py to load them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
