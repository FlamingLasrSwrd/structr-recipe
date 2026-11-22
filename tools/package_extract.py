"""Pin the package sizes FDC Branded Foods gives the foods data/packages.toml has rules for.

    python3 tools/package_extract.py --fetch 2026-10-29   # download that release's branded CSV zip (~450 MB)
    python3 tools/package_extract.py                      # count from the newest zip in .cache/fdc/
    python3 tools/package_extract.py --report             # also print each food's count beside its estimate

Reads FoodData_Central_branded_food_csv_<release>.zip from the git-ignored .cache/fdc/ (from
https://fdc.nal.usda.gov/download-datasets/), straight from the zip: branded_food.csv (its
package_weight, category, owner, market, channel) and food.csv (descriptions). One pass each,
streamed; it keeps only products in a category some rule names, so it needs a few hundred MB of
memory, not the files' 1.3 GB.

Writes data/packages/fdc.json: for each food with an `fdc` rule, the rule, how many products and
brand owners it matched, and the most common sizes (mealplanner/fdc_packages.py says how they are
counted). Sorted, so a re-run changes nothing unless the rules or the data did. Commit it, then
load with tools/import_packages.py.
"""

import argparse
import csv
import glob
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import fdc_packages
from mealplanner.packages import _ounces, read_packages
from mealplanner.profiles import ProfileError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "fdc")
URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_branded_food_csv_{release}.zip"
NAME = re.compile(r"FoodData_Central_branded_food_csv_(\d{4}-\d{2}-\d{2})\.zip$")
csv.field_size_limit(1 << 30)


def fetch(release: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"FoodData_Central_branded_food_csv_{release}.zip")
    print(f"downloading {URL.format(release=release)} ...")
    with urllib.request.urlopen(URL.format(release=release), timeout=600) as response, open(path + ".part", "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    os.replace(path + ".part", path)
    return path


def newest() -> str | None:
    found = sorted(p for p in glob.glob(os.path.join(CACHE, "FoodData_Central_branded_food_csv_*.zip")) if NAME.search(p))
    return found[-1] if found else None


def _rows(archive: zipfile.ZipFile, name: str):
    (member,) = [m for m in archive.namelist() if m.endswith("/" + name) or m == name]
    with archive.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def products(path: str, rules: dict):
    """One dict per GTIN, its latest record, for the products in a category some rule names."""
    categories = re.compile("|".join(f"(?:{r['category']})" for r in rules.values()), re.I)
    latest: dict[str, tuple] = {}
    with zipfile.ZipFile(path) as archive:
        for r in _rows(archive, "branded_food.csv"):
            gtin = r["gtin_upc"].lstrip("0") or "fdc" + r["fdc_id"]
            when = (r["modified_date"] or r["available_date"] or "", int(r["fdc_id"]))
            if gtin in latest and latest[gtin][0] >= when:
                continue
            keep = None
            if categories.search(r["branded_food_category"] or "") and r["package_weight"].strip():
                keep = {k: r[k] for k in ("branded_food_category", "brand_owner", "package_weight", "market_country",
                                          "discontinued_date", "trade_channel")}
            latest[gtin] = (when, keep)
        wanted = {when[1]: keep for when, keep in latest.values() if keep}
        del latest
        for r in _rows(archive, "food.csv"):
            keep = wanted.get(int(r["fdc_id"]))
            if keep is not None:
                keep["description"] = r["description"]
    return list(wanted.values())


def report(entries, pin: dict) -> None:
    for e in entries:
        if not e.fdc:
            continue
        count = pin["foods"][e.food]
        common = fdc_packages.common_sizes(count)
        top = ", ".join(f"{oz:g} ({n * 100 // max(count['products'], 1)}%, {o})" for oz, n, o in count["sizes"][:5])
        estimate = ", ".join(f"{_ounces(s):.4g}" for s in e.sizes)
        chosen = ", ".join(f"{oz:g}" for oz, *_ in common) or "(estimate stands)"
        print(f"{e.food[:34]:34} {count['products']:5} {count['owners']:4} | est {estimate:16} | FDC {chosen:22} | {top}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", metavar="RELEASE", help="download this release's zip first, e.g. 2026-10-29")
    parser.add_argument("--dataset", help="the zip to read (default: the newest in .cache/fdc/)")
    parser.add_argument("--report", action="store_true", help="print each food's count beside its estimate")
    args = parser.parse_args(argv)
    try:
        entries = read_packages(ROOT)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    rules = {e.food: e.fdc for e in entries if e.fdc}
    path = fetch(args.fetch) if args.fetch else (args.dataset or newest())
    if not path or not os.path.exists(path):
        print(f"problem: no FoodData_Central_branded_food_csv_<release>.zip in {CACHE} (use --fetch RELEASE)")
        return 1
    release = NAME.search(os.path.basename(path))
    found = products(path, rules)
    counts = fdc_packages.tally(found, rules)
    pin = {"source": {"dataset": fdc_packages.DATASET, "file": os.path.basename(path),
                      "release": release.group(1) if release else "", "citation": fdc_packages.CITATION},
           "foods": {food: {"rule": rules[food], **counts[food]} for food in sorted(rules)}}
    os.makedirs(os.path.dirname(os.path.join(ROOT, fdc_packages.PIN)), exist_ok=True)
    with open(os.path.join(ROOT, fdc_packages.PIN), "w", encoding="utf-8") as fh:
        text = json.dumps(pin, indent=1, sort_keys=True)
        fh.write(re.sub(r"\[\s+([0-9.]+),\s+(\d+),\s+(\d+)\s+\]", r"[\1, \2, \3]", text) + "\n")   # a size on one line
    standing = sum(1 for c in counts.values() if fdc_packages.common_sizes(c))
    print(f"{len(found)} products in the rules' categories; {len(rules)} foods counted, {standing} with common sizes; "
          f"wrote {fdc_packages.PIN}")
    if args.report:
        report(entries, pin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
