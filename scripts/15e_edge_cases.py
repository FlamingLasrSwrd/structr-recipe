"""Edge-case exploration: insufficient stock (invariant 15, found by the
overdraws() audit rather than refused at write time) and leftover
consumption (consumes_leftover_from, schema built two sessions ago, never
actually exercised with real data). Both are genuine probes -- some things
here are EXPECTED to reveal gaps, not just confirm success.

Run with: python3 scripts/15e_edge_cases.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrError
from mealplanner.connection import connect
from mealplanner.typetree import dt
from mealplanner.inventory import current_magnitude, overdraws

P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def main():
    client = connect()
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    print("=" * 70)
    print("EDGE CASE 1: insufficient stock (invariant 15)")
    print("=" * 70)
    print("Invariant 15: 'Summed input quantities per bearer cannot exceed "
          "that bearer's physical on-hand at the time of the Process.'")
    print("Not a write-time check (a validator would have to compute on-hand "
          "inside StructrScript, which cannot): recording an oversized "
          "Allocation is accepted, and mealplanner.inventory.overdraws() is "
          "how it is found. Probing both halves.\n")

    baseline_time = now - timedelta(hours=2)
    used_time = now - timedelta(hours=1)
    beef_portion = client.upsert("PortionOfSubstance", "name", f"{P}edge-case beef portion (only 200g on hand)", {
        "instanceOf": dt(client, "Beef (raw)"),
    })
    beef_quality = client.upsert("Quality", "name", f"{P}edge-case beef portion mass Quality", {
        "hasKind": dt(client, "Mass"), "inheresIn": beef_portion,
    })
    beef_measurement = client.upsert("Measurement", "name", f"{P}edge-case beef portion mass observation", {
        "value": 200.0, "unit": "g", "status": "observed", "hasTime": baseline_time.strftime(FMT), "isAboutQuality": beef_quality,
    })
    use_region = client.upsert("TemporalRegion", "name", f"{P}edge-case use region", {"hasBeginning": used_time.strftime(FMT)})
    use_process = client.upsert("Process", "name", f"{P}edge-case process using 500 g", {"occupiesTemporalRegion": use_region})
    print(f"Created a real 200g beef portion. current_magnitude confirms: "
          f"{current_magnitude(client, beef_quality, now)}g")

    oversized_measurement = client.post("/structr/rest/Measurement", {
        "name": f"{P}edge-case oversized allocation quantity", "value": 500.0, "unit": "g",
        "status": "observed", "hasTime": used_time.strftime(FMT), "visibleToAuthenticatedUsers": True,
    })["result"][0]
    failures = []
    alloc_id = None
    try:
        alloc_id = client.post("/structr/rest/Allocation", {
            "name": f"{P}edge-case allocation exceeding on-hand mass",
            "isAbout": beef_portion, "process": use_process, "hasParticipationRole": "input",
            "hasActualQuantity": oversized_measurement, "visibleToAuthenticatedUsers": True,
        })["result"][0]
        print(f"Allocating 500g from the 200g portion was accepted (id={alloc_id}), as designed: "
              f"the check is an audit, not a write-time rule.")
    except StructrError as e:
        failures.append("the oversized Allocation was rejected at write time (unexpected)")
        print(f"Rejected: {e.body} -- unexpected, invariant 15 was meant to be an audit.")

    if alloc_id:
        portion = client.get_all("PortionOfSubstance", beef_portion)["result"]
        found = overdraws(client, portion)
        # 200 g on hand, 500 g used: short by 300, and the baseline is observed so it is a real violation
        ok = len(found) == 1 and abs(found[0].shortfall_grams - 300.0) < 1e-6 and found[0].fatal
        print(f"  [{'OK' if ok else 'FAIL'}] overdraws() reports one violation, 300 g short, against an "
              f"observed baseline (got {[(o.shortfall_grams, o.baseline_status) for o in found]})")
        if not ok:
            failures.append("overdraws() did not report the 300 g overdraw")
        level = current_magnitude(client, beef_quality, now)
        ok = level is not None and abs(level - (-300.0)) < 1e-6
        print(f"  [{'OK' if ok else 'FAIL'}] current_magnitude is now -300 g (got {level})")
        if not ok:
            failures.append("current_magnitude did not go to -300 g")
        client.delete(f"/structr/rest/Allocation/{alloc_id}")

    client.delete(f"/structr/rest/Process/{use_process}")
    client.delete(f"/structr/rest/TemporalRegion/{use_region}")
    client.delete(f"/structr/rest/PortionOfSubstance/{beef_portion}")
    client.delete(f"/structr/rest/Quality/{beef_quality}")
    client.delete(f"/structr/rest/Measurement/{beef_measurement}")
    client.delete(f"/structr/rest/Measurement/{oversized_measurement}")
    print("(probe data cleaned up)")
    if failures:
        print(f"\nFAILED ({len(failures)}): " + "; ".join(failures))
        sys.exit(1)

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
