"""Make what remembered storage places need (mealplanner/places.py; docs/pantry.md, "Where each food goes"):
the "Storage Place Reference" hierarchy, the default kind "Storage Place", and everyone's level, "Storage
places -- everyone", each seen by every signed-in user.

Until it runs, a purchase still goes where the rule says, and a place someone picks is not remembered (the
booking says so). A household's and a person's levels are made by the bookings that first need them, private
to them. No schema change, so no restart: a remembered place is a DefaultSpecification on a level, keyed by
the food, whose targetType (on DefaultSpecification since scripts/05) is the storage condition.

Shared vocabulary only, idempotent (a second run makes nothing): run it on the owner's instance too
(owner_data_ok=True).

Run with: python3 scripts/52a_storage_places.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import places
from mealplanner.connection import connect


def main() -> int:
    client = connect(owner_data_ok=True)        # shared vocabulary only: the owner's instance needs it as well
    client.wait_until_ready()
    made = places.ensure_vocabulary(client)
    print(f"[1] Storage places: {'made ' + ', '.join(made) if made else 'all there already'}")
    if not places.installed(client):
        print("problem: the kind or everyone's level is still missing")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
