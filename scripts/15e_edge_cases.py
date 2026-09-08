"""Edge-case exploration: insufficient stock (invariant 15, never
tested before this) and leftover consumption (consumes_leftover_from,
schema built two sessions ago, never actually exercised with real
data). Both are genuine probes -- some things here are EXPECTED to
reveal gaps, not just confirm success.

Run with: python3 scripts/15e_edge_cases.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient, StructrError
from mealplanner.inventory import current_magnitude, physical_on_hand

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name):
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    print("=" * 70)
    print("EDGE CASE 1: insufficient stock (invariant 15) -- never tested")
    print("=" * 70)
    print("Invariant 15: 'Summed input quantities per bearer cannot exceed "
          "that bearer's physical on-hand at the time of the Process.'")
    print("No onCreate check for this exists anywhere in the build. Probing "
          "to see what actually happens when an Allocation's actual "
          "quantity exceeds the bearer's on-hand mass.\n")

    beef_portion = client.upsert("PortionOfSubstance", "name", f"{P}edge-case beef portion (only 200g on hand)", {
        "instanceOf": dt(client, "Beef (raw)"),
    })
    beef_quality = client.upsert("Quality", "name", f"{P}edge-case beef portion mass Quality", {
        "hasKind": dt(client, "Mass"), "inheresIn": beef_portion,
    })
    beef_measurement = client.upsert("Measurement", "name", f"{P}edge-case beef portion mass observation", {
        "value": 200.0, "unit": "g", "status": "observed", "hasTime": now.strftime(FMT), "isAboutQuality": beef_quality,
    })
    print(f"Created a real 200g beef portion. current_magnitude confirms: "
          f"{current_magnitude(client, beef_quality, now)}g")

    oversized_measurement = client.post("/structr/rest/Measurement", {
        "name": f"{P}edge-case oversized allocation quantity", "value": 500.0, "unit": "g",
        "status": "observed", "hasTime": now.strftime(FMT), "visibleToAuthenticatedUsers": True,
    })["result"][0]
    try:
        alloc_id = client.post("/structr/rest/Allocation", {
            "name": f"{P}edge-case allocation exceeding on-hand mass",
            "isAbout": beef_portion, "hasParticipationRole": "input",
            "hasActualQuantity": oversized_measurement, "visibleToAuthenticatedUsers": True,
        })["result"][0]
        print(f"\n*** GAP CONFIRMED: allocating 500g from a 200g on-hand portion "
              f"was ACCEPTED (id={alloc_id}). Invariant 15 is not enforced anywhere "
              f"in this build. ***")
        client.delete(f"/structr/rest/Allocation/{alloc_id}")
    except StructrError as e:
        print(f"\nRejected: {e.body} -- invariant 15 IS enforced somewhere (unexpected, investigate).")

    client.delete(f"/structr/rest/PortionOfSubstance/{beef_portion}")
    client.delete(f"/structr/rest/Quality/{beef_quality}")
    client.delete(f"/structr/rest/Measurement/{beef_measurement}")
    client.delete(f"/structr/rest/Measurement/{oversized_measurement}")
    print("(probe data cleaned up)")

    print("\n" + "=" * 70)
    print("EDGE CASE 2: leftover consumption lifecycle -- consumes_leftover_from")
    print("never exercised with real data before this")
    print("=" * 70)

    chicken_plan = client.get("/structr/rest/Plan", params={"name": f"{P}Braised Chicken Breast v1"})["result"][0]["id"]
    chicken_output_portion = client.get(
        "/structr/rest/PortionOfSubstance", params={"name": f"{P}Braised Chicken Breast output portion"}
    )["result"][0]["id"]

    meal_plan_id = client.upsert("MealPlan", "name", f"{P}Leftover test week", {
        "timeBudgetMinutes": 60.0, "timeBudgetWeight": 0.4, "varietyWeight": 0.3,
        "stockWeight": 0.2, "wasteWeight": 0.2,
    })
    week_region = client.upsert("TemporalRegion", "name", f"{P}Leftover test week temporal region", {
        "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(days=7)).strftime(FMT),
    })
    client.patch(f"/structr/rest/MealPlan/{meal_plan_id}", {"isAbout": week_region})

    source_region = client.upsert("TemporalRegion", "name", f"{P}Monday dinner region (source cook)", {
        "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(hours=2)).strftime(FMT),
    })
    source_entry_id = client.upsert("MealPlanEntry", "name", f"{P}Monday dinner -- fresh braised chicken", {
        "memberOf": meal_plan_id, "isAbout": source_region,
        "references": chicken_plan, "hasPlannedServings": 4.0, "isSkipped": False,
    })
    print(f"Source entry (fresh cook, 4 servings): {source_entry_id}")

    leftover_region = client.upsert("TemporalRegion", "name", f"{P}Wednesday lunch region (leftovers)", {
        "hasBeginning": (now + timedelta(days=2)).strftime(FMT), "hasEnd": (now + timedelta(days=2, hours=1)).strftime(FMT),
    })
    leftover_entry_id = client.upsert("MealPlanEntry", "name", f"{P}Wednesday lunch -- leftover chicken", {
        "memberOf": meal_plan_id, "isAbout": leftover_region,
        "consumesLeftoverFrom": source_entry_id, "isSkipped": False,
    })
    print(f"Leftover entry (consumes_leftover_from source): {leftover_entry_id}")

    print("\nVerification...")
    entry = client.get_all("MealPlanEntry", leftover_entry_id)["result"]
    ok1 = (entry.get("consumesLeftoverFrom") or {}).get("id") == source_entry_id
    print(f"  [{'OK' if ok1 else 'FAIL'}] leftover entry correctly points at source entry")

    source = client.get_all("MealPlanEntry", source_entry_id)["result"]
    reverse = {e["id"] for e in source.get("sourceForLeftoverEntries", [])}
    ok2 = leftover_entry_id in reverse
    print(f"  [{'OK' if ok2 else 'FAIL'}] reverse collection (source.sourceForLeftoverEntries) includes it")

    print("\n  Invariant 27a check (Role/consumes_leftover_from consistency): "
          "requires a reservation Role on the physical leftover portion pointing "
          "back at the consuming MealPlanEntry. NO RELATION FOR THIS EXISTS in "
          "the build -- Role has no relationship to MealPlanEntry at all. This is "
          "a genuine gap, not tested further here (see write-up).")

    if not (ok1 and ok2):
        print("\nFAILED.")
        sys.exit(1)
    print("\nCore leftover-consumption mechanism works. MealPlan/entries left in "
          "place as real test data (not cleaned up).")


if __name__ == "__main__":
    main()
