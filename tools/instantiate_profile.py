"""Instantiate a profile into the owner's own data, from their selection file (mealplanner/profiles.py).

    python3 tools/instantiate_profile.py nutrition private/nutrition.toml [--reset]
    python3 tools/instantiate_profile.py kitchen private/kitchen.toml
    python3 tools/instantiate_profile.py pantry private/pantry.toml [--reset]
    python3 tools/instantiate_profile.py nutrition --show "Adult male 31-50 moderately active"
    python3 tools/instantiate_profile.py pantry --show "Basic pantry"
    python3 tools/instantiate_profile.py kitchen --list [--profile "Everyday home kitchen"]
    python3 tools/instantiate_profile.py pantry --list [--profile "Basic pantry"]

--show prints what a dietary or pantry profile resolves to. --list prints every
equipment type or food, grouped, marking those the profile includes: the list to
choose from when editing private/kitchen.toml or private/pantry.toml. --reset
replaces targets or amounts the owner changed in Structr with the profile's
values. Idempotent otherwise.
"""

import argparse
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.profiles import (
    EQUIPMENT_HIERARCHY, ProfileError, dietary_targets, instantiate_kitchen, instantiate_nutrition, instantiate_pantry,
    kitchen_items, pantry_stock,
)
from mealplanner.vocabulary_import import FOOD_HIERARCHY


def show_targets(client, profile: str) -> None:
    for t in dietary_targets(client, profile):
        lo = "" if t.minimum is None else f"{t.minimum:g}"
        hi = "" if t.maximum is None else f"{t.maximum:g}"
        print(f"  {t.nutrient:40s} {lo:>9s} - {hi:<9s} {t.unit:5s} {t.status}")


def show_stock(client, profile: str) -> None:
    for name, qty in sorted(pantry_stock(client, profile).values()):
        print(f"  {name:40s} {qty['value']:>7g} {qty['unit']}")


def list_types(client, what: str, profile: str | None) -> None:
    """Every equipment type or food, as a tree, marking the profile's."""
    if what == "pantry":
        hierarchy = FOOD_HIERARCHY
        included = {name for name, _ in pantry_stock(client, profile).values()} if profile else set()
    else:
        hierarchy = EQUIPMENT_HIERARCHY
        included = {name for name, _ in kitchen_items(client, profile).values()} if profile else set()
    rows = [r for r in client.get_all("DomainType")["result"]
            if (r.get("hierarchy") or {}).get("name") == hierarchy]
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
    parser.add_argument("what", choices=["nutrition", "kitchen", "pantry"])
    parser.add_argument("selection", nargs="?", help="the owner's selection file")
    parser.add_argument("--show", metavar="PROFILE", help="print a dietary profile's targets or a pantry profile's stock")
    parser.add_argument("--list", action="store_true", help="print the equipment or foods to choose from")
    parser.add_argument("--profile", help="with --list: mark this profile's items")
    parser.add_argument("--reset", action="store_true", help="replace targets or amounts the owner changed")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # this is how the owner's own targets and kitchen get made
    client.wait_until_ready()
    try:
        if args.show:
            if args.what == "kitchen":
                parser.error("--show is for nutrition or pantry; use kitchen --list --profile")
            (show_targets if args.what == "nutrition" else show_stock)(client, args.show)
            return 0
        if args.list:
            if args.what == "nutrition":
                parser.error("--list is for kitchen or pantry")
            list_types(client, args.what, args.profile)
            return 0
        if not args.selection:
            parser.error("give a selection file, --show or --list")
        with open(args.selection, "rb") as fh:
            selection = tomllib.load(fh)
        if args.what == "nutrition":
            report = instantiate_nutrition(client, selection, reset=args.reset)
        elif args.what == "pantry":
            report = instantiate_pantry(client, selection, reset=args.reset)
        else:
            report = instantiate_kitchen(client, selection)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(f"{len(report.written)} written ({', '.join(f'{k} {v}' for k, v in report.counts.items())})")
    for line in report.kept:
        print(f"  kept, it differs from the profile (--reset replaces it): {line}")
    for line in report.removed:
        print(f"  removed: {line}")
    history = {"nutrition": "a meal plan uses it", "kitchen": "a cook used it",
               "pantry": "a cook used it or it was weighed"}[args.what]
    for line in report.refused:
        print(f"  not removed, {history}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
