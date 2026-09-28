"""Load the profile definitions in data/profiles/ into Structr (mealplanner/profiles.py).

    python3 tools/import_profiles.py            # load (after tools/import_vocabulary.py)
    python3 tools/import_profiles.py --check    # parse the files; write nothing

Idempotent. Meant for the owner's instance as well as any other; needs
STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.profiles import ProfileError, import_profiles, read_profiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="parse only; write nothing")
    args = parser.parse_args(argv)
    try:
        dietary, kitchen, pantry = read_profiles(ROOT)
        print(f"{len(dietary)} dietary profiles ({sum(len(p.intakes) for p in dietary)} intakes), "
              f"{len(kitchen)} kitchen profiles ({sum(len(p.items) for p in kitchen)} items), "
              f"{len(pantry)} pantry profiles ({sum(len(p.stock) for p in pantry)} items)")
        if args.check:
            return 0
        client = connect(owner_data_ok=True)
        client.wait_until_ready()
        counts = import_profiles(client, dietary, kitchen, pantry)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
