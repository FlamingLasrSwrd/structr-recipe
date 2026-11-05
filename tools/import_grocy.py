"""Import a Grocy pantry: its products as foods, its stock as Purchase bookings (docs/imports.md).

    python3 tools/import_grocy.py --fetch URL private/grocy/          # record an export (GROCY_API_KEY)
    python3 tools/import_grocy.py private/grocy/ --draft > private/grocy-map.toml   # then review it
    python3 tools/import_grocy.py private/grocy/ --map private/grocy-map.toml --check
    python3 tools/import_grocy.py private/grocy/ --map private/grocy-map.toml --timezone America/Edmonton

An export is one JSON file per Grocy REST object (products, quantity_units, quantity_unit_conversions,
locations, stock), as GET /api/objects/<name> returns it. The map file says which vocabulary food each
product is: a match is the owner's judgment (J19), so the importer never makes one; --draft proposes
them for review, and only a product the map names is booked. --check reads no instance and writes
nothing: it reports what an import would write and why it leaves out the rest. Without --check it
books through mealplanner/pantry.py, on STRUCTR_URL with STRUCTR_TOOLS_PASSWORD, and an import run
twice writes nothing new.
"""

import argparse
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import grocy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCABULARY = os.path.join(ROOT, "data", "vocabulary.toml")


def fetch(url: str, directory: str, key: str, opener=urllib.request.urlopen) -> list[str]:
    """Record an export: each REST object into <directory>/<object>.json. Returns the files written."""
    os.makedirs(directory, exist_ok=True)
    written = []
    for name in grocy.OBJECTS:
        request = urllib.request.Request(f"{url.rstrip('/')}/api/objects/{name}",
                                         headers={"GROCY-API-KEY": key, "Accept": "application/json"})
        with opener(request) as response:
            rows = json.load(response)
        if not isinstance(rows, list):
            raise grocy.GrocyError(f"{name}: Grocy answered with something other than a list of rows")
        path = os.path.join(directory, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        written.append(path)
    return written


def report(the_plan: grocy.Plan, vocabulary: grocy.Vocabulary) -> None:
    p = the_plan
    print(f"Foods: {len(p.matched)} product(s) matched in the map, {len(p.proposed)} not matched, "
          f"{len(p.not_food)} not foods here, {len(p.inactive)} inactive in Grocy")
    for product, food in sorted(p.matched.items()):
        print(f"  matched      {product} -> {food}   (the map)")
    for product, found in sorted(p.proposed.items()):
        if found:
            print(f"  not matched  {product}: alike in the vocabulary, for review: {', '.join(found)}")
        else:
            print(f"  not matched  {product}: nothing alike in the vocabulary (a new food to add, or not a food)")
    for product in p.not_food:
        print(f"  not a food   {product}   (the map)")
    for product in p.inactive:
        print(f"  inactive     {product}")
    print("Locations:")
    for location, (storage, why) in p.storage.items():
        print(f"  {location} -> {storage or '?'}   ({why})")
    print(f"Purchases it would book: {len(p.bookings)}")
    for b in p.bookings:
        print(f"  {b.token}: {b.amount:g} {b.unit} {b.food} ({b.product}), bought {b.purchased.isoformat()}, "
              f"in the {b.storage.lower()}" + (", opened" if b.opened else ""))
    print(f"Stock entries it would not book: {len(p.not_booked)}")
    for entry, product, why in p.not_booked:
        print(f"  entry {entry} ({product}): {why}")
    if p.facts:
        print("What Grocy's conversions state, for the vocabulary (not written; see docs/imports.md):")
    for f in p.facts:
        food = p.matched.get(f.product)
        if f.kind == "each":
            has, what = food in vocabulary.each, f"{f.grams:g} g per {f.unit}"
        elif f.kind == "density":
            has, what = food in vocabulary.volume, f"{f.grams:g} g per ml (from {f.unit})"
        else:
            has, what = False, f"a {f.unit} is {f.grams:g} g: a package size, for the later \"what it is sold in\""
        where = (f" -> {food}" + (", which the vocabulary already gives one" if has else ", which the vocabulary lacks")
                 if food and f.kind != "package" else "")
        print(f"  {f.product}: {what}{where}" + ("  (a conversion Grocy states for every product)" if f.general else ""))
    print("Left for a later stage: " + ", ".join(f"{n} {what}" for what, n in p.later.items())
          + ", the shopping list, recipes")
    for problem in p.problems:
        print(f"problem: {problem}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", help="the directory of the export's JSON files")
    parser.add_argument("--map", help="the owner's map file (TOML): [foods] and [locations]")
    parser.add_argument("--check", action="store_true", help="report what it would write; read no instance")
    parser.add_argument("--draft", action="store_true", help="print a map file for the owner to review")
    parser.add_argument("--timezone", help="where the purchases were made, for their dates (e.g. America/Edmonton)")
    parser.add_argument("--vocabulary", default=VOCABULARY)
    parser.add_argument("--fetch", metavar="URL", help="record an export from this Grocy into EXPORT first")
    args = parser.parse_args(argv)
    try:
        if args.fetch:
            key = os.environ.get("GROCY_API_KEY")
            if not key:
                print("problem: --fetch needs GROCY_API_KEY (Grocy: Settings, Manage API keys)")
                return 1
            for path in fetch(args.fetch, args.export, key):
                print(f"recorded {path}")
            if not (args.check or args.draft or args.map):
                return 0
        export = grocy.read_export(args.export)
        vocabulary = grocy.read_vocabulary_foods(args.vocabulary)
        mapping = grocy.read_mapping(args.map)
    except (grocy.GrocyError, OSError, ValueError) as exc:
        print(f"problem: {exc}")
        return 1
    if args.draft:
        sys.stdout.write(grocy.draft_map(export, vocabulary, mapping))
        return 0
    the_plan = grocy.plan(export, mapping, vocabulary)
    report(the_plan, vocabulary)
    if args.check:
        return 1 if the_plan.problems else 0
    if the_plan.problems:
        print("problem: the map has problems (above); nothing booked")
        return 1
    if not args.timezone:
        print("problem: booking needs --timezone, for the day each purchase was made")
        return 1
    from mealplanner.connection import connect
    client = connect(owner_data_ok=True)        # the owner's own pantry, imported from its own export
    client.wait_until_ready()
    failed = 0
    for booked in grocy.book(client, the_plan, ZoneInfo(args.timezone)):
        b = booked.buy
        if booked.problem:
            failed += 1
            print(f"problem: {b.token} ({b.product}): {booked.problem}")
        else:
            print(f"{b.token}: " + (f"wrote {booked.created} node(s)" if booked.created else "booked before; nothing new written"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
