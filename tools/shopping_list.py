"""The shopping list for a committed week (mealplanner/shopping.py).

    python3 tools/shopping_list.py private/week.toml

What the week's committed, not yet cooked meals need, less what the pantry holds, grouped by the
day each food is first needed, with an estimated cost at the week file's price level (`prices`).
Read-only: a shopping list is computed, never stored (data-model.md Sec 7, AcquisitionList).
Needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import sys
import tomllib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.prices import price_table
from mealplanner.profiles import ProfileError
from mealplanner.shopping import describe, shopping_list


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("week", help="the week file, e.g. private/week.toml")
    args = parser.parse_args(argv)
    with open(args.week, "rb") as fh:
        week = tomllib.load(fh)
    name = week.get("name") or f"Week of {week['start'].isoformat()}"
    zone = ZoneInfo(week.get("timezone", "UTC"))
    client = connect(owner_data_ok=True)     # read-only
    client.wait_until_ready()
    plans = client.get("/structr/rest/MealPlan", params={"name": name})["result"]
    if len(plans) != 1:
        print(f"problem: no single MealPlan named {name!r}: propose and commit the week first (tools/plan_week.py)")
        return 1
    prices = None
    if week.get("prices"):
        try:
            prices = price_table(client, week["prices"])
        except ProfileError as exc:
            print(f"problem: {'; '.join(exc.problems)}")
            return 1
    shopping = shopping_list(client, plans[0]["id"], datetime.now(timezone.utc), prices)
    if not shopping.cooks:
        print(f"{name} has no meals to cook yet: commit the week first (tools/plan_week.py --commit)")
        return 1
    print(describe(shopping, zone, week.get("prices")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
