"""Set up the owner's household: its people, and each person's targets and baseline (mealplanner/household.py).

    python3 tools/instantiate_household.py private/household.toml [--reset]

--reset replaces targets someone changed in Structr with their profile's values. Idempotent
otherwise. Needs the dietary profiles loaded (tools/import_profiles.py) and each baseline's
recipe file loaded (tools/import_recipe.py).
"""

import argparse
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.household import instantiate_household
from mealplanner.profiles import ProfileError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("selection", help="the household file, e.g. private/household.toml")
    parser.add_argument("--reset", action="store_true", help="replace targets someone changed in Structr")
    args = parser.parse_args(argv)
    with open(args.selection, "rb") as fh:
        selection = tomllib.load(fh)
    client = connect(owner_data_ok=True)     # the owner's household is their own data
    client.wait_until_ready()
    try:
        report = instantiate_household(client, selection, ROOT, reset=args.reset)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(f"household {report.household!r}: {', '.join(report.members)}")
    for person, r in report.people.items():
        line = f"  {person}: {len(r.written)} targets written"
        if r.adopted:
            line += f", {len(r.adopted)} adopted from before there were people"
        if report.baselines.get(person):
            line += f"; baseline {', '.join(report.baselines[person])}"
        print(line)
        for kept in r.kept:
            print(f"    kept, it differs from the profile (--reset replaces it): {kept}")
        for refused in r.refused:
            print(f"    not removed, a meal plan uses it: {refused}")
    print("people and household: " + ", ".join(f"{k} {v}" for k, v in report.counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
