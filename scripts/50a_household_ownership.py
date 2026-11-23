"""Make an instance's existing data its household's own (Path S stage 5; docs/verification-and-sharing.md
§3.4, "Who owns what"; mealplanner/ownership.py).

Until now every node was seen by every signed-in user, and the pages booked as the superuser. This moves
the data of an instance's one household over: its weeks, bookings, stock, kitchen, pantry levels, own
price and package levels and own recipes become private to the household, each person's targets,
exclusions and baseline private to them (the household may read them), and shared knowledge (the
vocabulary, profiles, public levels and recipes, products and barcodes) stays shared. It also makes the
pantry's kinds of booking, which a household's booking finds and never makes.

A data migration, idempotent: a second run changes nothing. An instance with no household (a development
stack, which tools/rebuild.sh builds) is left as it is; one with several is refused. Run it on the owner's
instance (owner_data_ok=True) after a backup (docs/backups.md) and after tools/install_methods.py, which
installs the rule it applies (methods/claimHousehold.js). No schema change, so no restart is needed.

Run with: python3 scripts/50a_household_ownership.py [--check]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import ownership
from mealplanner.connection import connect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="say what would change, and change nothing")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # the owner's household is the one this is for
    client.wait_until_ready()

    found = ownership.households(client)
    if not found:
        print("no household on this instance: nothing to do")
        return 0
    if len(found) > 1:
        print(f"problem: {len(found)} households on this instance; this moves the data of an instance of one")
        return 1
    if not args.check:
        made = ownership.ensure_operations(client)
        print(f"[1] Pantry operations: {', '.join(made) if made else 'all there already'}")
    print(f"[2] {'What would change' if args.check else 'Ownership'} for {found[0]['name']!r}...")
    try:
        done = ownership.claim(client, ROOT, check=args.check)
    except ownership.OwnershipError as exc:
        print(f"problem: {exc}")
        return 1
    for type_name, n in sorted(done.counts.items()):
        print(f"    {type_name}: {n}")
    if args.check:
        print(f"    {sum(done.counts.values())} node(s) to change; {done.owned} belong to the household or its people")
    else:
        print(f"    {done.changed} node(s) changed; {done.owned} belong to the household or its people; {done.remaining} left")
    return 1 if done.remaining and not args.check else 0


if __name__ == "__main__":
    sys.exit(main())
