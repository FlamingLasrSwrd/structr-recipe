"""Load the public package sizes into Structr (mealplanner/packages.py, data/packages.toml).

    python3 tools/import_packages.py            # load (after tools/import_vocabulary.py)
    python3 tools/import_packages.py --check    # read the file against data/vocabulary.toml; write nothing

Idempotent; a size the file no longer names is removed. The owner's own sizes are a level below
this one, from private/packages.toml (tools/instantiate_profile.py packages).
"""

import argparse
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.packages import PUBLIC_LEVEL, check_against_vocabulary, import_packages, read_packages
from mealplanner.profiles import ProfileError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="read only; write nothing")
    args = parser.parse_args(argv)
    try:
        entries = read_packages(ROOT)
        with open(os.path.join(ROOT, "data/vocabulary.toml"), "rb") as fh:
            problems = check_against_vocabulary(entries, tomllib.load(fh))
        if problems:
            raise ProfileError(problems)
        print(f"{len(entries)} foods, {sum(len(e.sizes) for e in entries)} sizes, on {PUBLIC_LEVEL!r}")
        if args.check:
            return 0
        client = connect(owner_data_ok=True)
        client.wait_until_ready()
        counts = import_packages(client, entries)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
