"""Demonstrates mealplanner/reservation.py end to end, fixing the "no
reservation layer" gap found by external review: two candidates scored
in the same planning session used to both see the full on-hand stock as
available, because nothing accounted for what an already-committed
MealPlanEntry claims.

Uses its OWN MealPlan ("TEST -- Reservation demo week"), not
scripts/11c_simple_selector.py's "TEST -- Selector demo week" -- an
earlier version of this script reused that one and left a committed
entry behind, which would have silently changed that script's own
baseline demo output on every future run. Exactly the test-isolation
risk external review flagged (self-reported findings checklist, item
on test-state contamination) -- caught before it landed, not after.

Commits ONE MealPlanEntry for "TEST -- Beef and Broccoli Stir-Fry v1" at
4.0 planned servings (double the recipe's own 2.0-serving yield, so it
claims 800g beef / 600g broccoli -- more than the 450g/350g on hand),
then shows:
  1. committed_requirements() correctly sums that claim,
  2. the selector's stock-coverage score for a SECOND helping of the
     same recipe correctly collapses (previously would have shown 100%
     coverage twice against the same physical stock),
  3. net_requirements() (AcquisitionList's formula) produces a real,
     positive shopping-list entry for the shortfall.

Run with: python3 scripts/20a_reservation_demo.py
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))

from structr_client import StructrClient
from mealplanner.reservation import committed_requirements, net_requirements

# scripts/11c_simple_selector.py's filename starts with a digit, so it
# can't be `import`ed as a normal module -- loaded directly by path
# instead, same script, no duplication of select()'s logic.
_spec = importlib.util.spec_from_file_location(
    "selector_11c", os.path.join(SCRIPTS_DIR, "11c_simple_selector.py")
)
_selector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_selector)
select = _selector.select

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    meal_plan_id = client.upsert("MealPlan", "name", f"{P}Reservation demo week", {
        "timeBudgetMinutes": 30.0, "timeBudgetWeight": 0.8, "varietyWeight": 0.2,
    })
    beef_plan_id = client.get("/structr/rest/Plan", params={"name": f"{P}Beef and Broccoli Stir-Fry v1"})["result"][0]["id"]

    print("[0] Baseline: committed_requirements() before any entry exists...")
    before = committed_requirements(client, meal_plan_id)
    print(f"    {before or '{} (nothing committed yet)'}")

    print("\n[1] Committing one entry: Beef and Broccoli Stir-Fry at 4.0 planned "
          "servings (2x the recipe's own 2.0-serving yield -- claims 800g beef / "
          "600g broccoli, more than the 450g/350g actually on hand)...")
    region_id = client.upsert("TemporalRegion", "name", f"{P}Demo commitment window", {
        "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(hours=1)).strftime(FMT),
    })
    entry_id = client.upsert("MealPlanEntry", "name", f"{P}Demo commitment -- beef and broccoli x2 batch", {
        "memberOf": meal_plan_id, "isAbout": region_id,
        "references": beef_plan_id, "hasPlannedServings": 4.0, "isSkipped": False,
    })
    print(f"    entry={entry_id}")

    print("\n[2] committed_requirements() after committing...")
    reserved = committed_requirements(client, meal_plan_id)
    for type_id, grams in reserved.items():
        name = client.get_all("DomainType", type_id)["result"].get("name")
        print(f"    {name}: {grams:.0f}g reserved")

    print("\n[3] Selector run -- does a SECOND helping of the same recipe correctly "
          "see reduced availability?...")
    ranked = select(client, meal_plan_id, now)
    for r in ranked:
        name = r["plan"]["name"]
        if r["disqualified"]:
            print(f"    DISQUALIFIED  {name:45s}  {r['reason']}")
        else:
            print(f"    score={r['score']:.3f}  {name:45s}  {r['reason']}")

    print("\n[4] net_requirements() -- AcquisitionList's formula: does the "
          "over-committed shortfall show up as a real shopping-list entry?...")
    net = net_requirements(client, meal_plan_id, now)
    if not net:
        print("    (empty -- nothing needs buying)")
    for type_id, grams in net.items():
        name = client.get_all("DomainType", type_id)["result"].get("name")
        print(f"    BUY {grams:.0f}g of {name}")

    print("\nDone. Beef and Broccoli's stock-coverage score above should be near "
          "0%, not the 100% it would show scored in isolation -- and net_requirements() "
          "should show a positive shortfall for both Beef (raw) and Broccoli.")


if __name__ == "__main__":
    main()
