"""Load the public price levels into Structr (mealplanner/prices.py, data/prices.toml).

    python3 tools/import_prices.py            # load (after tools/import_vocabulary.py)
    python3 tools/import_prices.py --check    # read the file and the pins; write nothing

Idempotent; a price the file no longer names is removed. The owner's own prices are a level
below one of these, from private/prices.toml (tools/instantiate_profile.py prices).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.profiles import ProfileError
from mealplanner.prices import import_prices, level_prices, read_book

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="read only; write nothing")
    args = parser.parse_args(argv)
    try:
        book, bls, ppnap = read_book(ROOT)
        prices, problems = level_prices(book, bls, ppnap)
        if problems:
            raise ProfileError(problems)
        levels = {}
        for p in prices:
            levels[p.level] = levels.get(p.level, 0) + 1
        print(f"{len(book.entries)} foods priced: " + ", ".join(f"{n} on {level!r}" for level, n in levels.items()))
        if args.check:
            return 0
        client = connect(owner_data_ok=True)
        client.wait_until_ready()
        counts = import_prices(client, book, bls, ppnap)
    except ProfileError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
