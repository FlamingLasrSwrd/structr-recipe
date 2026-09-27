"""Instantiate a profile into the owner's own data, from their selection file (mealplanner/profiles.py).

    python3 tools/instantiate_profile.py nutrition private/nutrition.toml [--reset]
    python3 tools/instantiate_profile.py kitchen private/kitchen.toml
    python3 tools/instantiate_profile.py nutrition --show "Adult male 31-50 moderately active"
    python3 tools/instantiate_profile.py kitchen --list [--profile "Everyday home kitchen"]

--show prints the targets a dietary profile resolves to. --list prints every
equipment type, grouped, marking those the kitchen profile includes: the list to
choose from when editing private/kitchen.toml. --reset replaces targets the owner
changed in Structr with the profile's values. Idempotent otherwise.
"""

import argparse
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.profiles import (
    EQUIPMENT_HIERARCHY, ProfileError, dietary_targets, instantiate_kitchen, instantiate_nutrition, kitchen_items,
)


def show_targets(client, profile: str) -> None:
    for t in dietary_targets(client, profile):
        lo = "" if t.minimum is None else f"{t.minimum:g}"
        hi = "" if t.maximum is None else f"{t.maximum:g}"
        print(f"  {t.nutrient:40s} {lo:>9s} - {hi:<9s} {t.unit:5s} {t.status}")


def list_equipment(client, profile: str | None) -> None:
    included = {name for name, _ in kitchen_items(client, profile).values()} if profile else set()
    rows = [r for r in client.get_all("DomainType")["result"]
            if (r.get("hierarchy") or {}).get("name") == EQUIPMENT_HIERARCHY]
    children: dict[str | None, list[str]] = {}
    for r in rows:
        children.setdefault((r.get("parent") or {}).get("name"), []).append(r["name"])

    def walk(parent, depth):
        for name in sorted(children.get(parent, [])):
            mark = "[x]" if name in included else "[ ]"
            print(f"  {'  ' * depth}{mark if name not in children else '   '} {name}")
            walk(name, depth + 1)
    walk(None, 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("what", choices=["nutrition", "kitchen"])
    parser.add_argument("selection", nargs="?", help="the owner's selection file")
    parser.add_argument("--show", metavar="PROFILE", help="print a dietary profile's targets")
    parser.add_argument("--list", action="store_true", help="print the equipment to choose from")
    parser.add_argument("--profile", help="with --list: mark this kitchen profile's items")
    parser.add_argument("--reset", action="store_true", help="replace targets the owner changed")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # this is how the owner's own targets and kitchen get made
    client.wait_until_ready()
    try:
        if args.show:
            show_targets(client, args.show)
            return 0
        if args.list:
            list_equipment(client, args.profile)
            return 0
        if not args.selection:
            parser.error("give a selection file, --show or --list")
        with open(args.selection, "rb") as fh:
            selection = tomllib.load(fh)
        report = (instantiate_nutrition(client, selection, reset=args.reset) if args.what == "nutrition"
                  else instantiate_kitchen(client, selection))
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(f"{len(report.written)} written ({', '.join(f'{k} {v}' for k, v in report.counts.items())})")
    for line in report.kept:
        print(f"  kept, it differs from the profile (--reset replaces it): {line}")
    for line in report.removed:
        print(f"  removed: {line}")
    history = "a meal plan uses it" if args.what == "nutrition" else "a cook used it"
    for line in report.refused:
        print(f"  not removed, {history}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
