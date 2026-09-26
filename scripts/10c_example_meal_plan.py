"""An illustrative MealPlan tying together the recipes already built,
plus one StockPolicy and one NutritionTarget -- proving MealPlan.hasConstraint
is genuinely polymorphic across both PlanningConstraint subtypes through
one relationship declaration (Sec 13's "becomes one polymorphic
declaration").

TEST-marked throughout: this is an illustrative week, not the user's
actual schedule -- there's no real meal-plan data to curate yet.

Run with: python3 scripts/10c_example_meal_plan.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.typetree import dt

P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"

# Anchor the illustrative week on a real Monday for readability.
WEEK_START = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)  # a Monday
WEEK_END = WEEK_START + timedelta(days=7)


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] MealPlan for the week, with its TemporalRegion...")
    week_region = client.upsert("TemporalRegion", "name", f"{P}Week of 2026-09-07", {
        "hasBeginning": WEEK_START.strftime(FMT), "hasEnd": WEEK_END.strftime(FMT),
    })
    meal_plan_id = client.upsert("MealPlan", "name", f"{P}Meal plan for the week of 2026-09-07", {
        "isAbout": week_region,
    })
    print(f"    week_region={week_region}  meal_plan={meal_plan_id}")

    print("\n[2] Two entries, referencing the two real recipes already built...")
    chicken_plan = client.get("/structr/rest/Plan", params={"name": "Braised Chicken Breast v1"})["result"][0]["id"]
    pasta_plan = client.get("/structr/rest/Plan", params={"name": f"{P}Boiled Pasta v1"})["result"][0]["id"]

    tue_region = client.upsert("TemporalRegion", "name", f"{P}Tuesday dinner 2026-09-08", {
        "hasBeginning": (WEEK_START + timedelta(days=1, hours=18)).strftime(FMT),
        "hasEnd": (WEEK_START + timedelta(days=1, hours=20)).strftime(FMT),
    })
    entry1_id = client.upsert("MealPlanEntry", "name", f"{P}Tuesday dinner -- braised chicken breast", {
        "memberOf": meal_plan_id, "isAbout": tue_region,
        "references": chicken_plan, "hasPlannedServings": 2.0, "isSkipped": False,
    })

    thu_region = client.upsert("TemporalRegion", "name", f"{P}Thursday dinner 2026-09-10", {
        "hasBeginning": (WEEK_START + timedelta(days=3, hours=18)).strftime(FMT),
        "hasEnd": (WEEK_START + timedelta(days=3, hours=20)).strftime(FMT),
    })
    entry2_id = client.upsert("MealPlanEntry", "name", f"{P}Thursday dinner -- boiled pasta", {
        "memberOf": meal_plan_id, "isAbout": thu_region,
        "references": pasta_plan, "hasPlannedServings": 2.0, "isSkipped": False,
    })
    print(f"    entry1(chicken)={entry1_id}  entry2(pasta)={entry2_id}")

    print("\n[3] StockPolicy: keep chicken breast on hand (500g reorder, 1500g target, "
          "fridge, sealed only)...")
    reorder_qty = client.upsert("QuantitySpecification", "name", f"{P}chicken reorder threshold -- 500g", {"value": 500.0, "unit": "g", "status": "specified"})
    target_qty = client.upsert("QuantitySpecification", "name", f"{P}chicken target level -- 1500g", {"value": 1500.0, "unit": "g", "status": "specified"})
    stock_policy_id = client.upsert("StockPolicy", "name", f"{P}Keep chicken breast on hand", {
        "appliesTo": dt(client, "Chicken Breast (raw)"),
        "hasReorderThreshold": reorder_qty, "hasTargetLevel": target_qty,
        "includesSubtypes": True, "eligibleStorageConditions": [dt(client, "Fridge")],
        "eligibleWhenOpened": False, "eligibleWhenSealed": True,
    })
    print(f"    reorder={reorder_qty} target={target_qty} policy={stock_policy_id}")

    print("\n[4] NutritionTarget: 50-80g protein daily (open comparison -- an actual "
          "range, exercising the min/max support just added)...")
    protein_range = client.upsert("QuantitySpecification", "name", f"{P}daily protein target range -- 50 to 80g", {
        "minValue": 50.0, "maxValue": 80.0, "unit": "g", "status": "specified",
    })
    nutrition_target_id = client.upsert("NutritionTarget", "name", f"{P}Daily protein target", {
        "forNutrient": dt(client, "Protein"), "hasTargetRange": protein_range,
        "hasTimeScope": "daily", "dayBoundaryRule": "midnight",
    })
    print(f"    range={protein_range} target={nutrition_target_id}")

    print("\n[5] MealPlan.hasConstraint -> BOTH the StockPolicy and the NutritionTarget, "
          "through ONE polymorphic relationship declaration...")
    client.patch(f"/structr/rest/MealPlan/{meal_plan_id}", {"hasConstraint": [stock_policy_id, nutrition_target_id]})

    print("\n[6] Verification...")
    all_ok = True

    mp = client.get_all("MealPlan", meal_plan_id)["result"]
    entries = {e["id"] for e in mp.get("hasEntry", [])}
    constraints = {c["id"]: c["type"] for c in mp.get("hasConstraint", [])}
    ok = entries == {entry1_id, entry2_id}
    print(f"    [{'OK' if ok else 'FAIL'}] MealPlan.hasEntry contains both entries")
    all_ok &= ok
    ok = constraints == {stock_policy_id: "StockPolicy", nutrition_target_id: "NutritionTarget"}
    print(f"    [{'OK' if ok else 'FAIL'}] MealPlan.hasConstraint polymorphically contains "
          f"BOTH a StockPolicy and a NutritionTarget: {constraints}")
    all_ok &= ok

    e1 = client.get_all("MealPlanEntry", entry1_id)["result"]
    ok = (
        (e1.get("memberOf") or {}).get("id") == meal_plan_id
        and (e1.get("references") or {}).get("id") == chicken_plan
        and e1.get("hasPlannedServings") == 2.0
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Entry 1: memberOf/references/plannedServings correct")
    all_ok &= ok

    sp = client.get_all("StockPolicy", stock_policy_id)["result"]
    sp_target = client.get_all("QuantitySpecification", (sp.get("hasTargetLevel") or {}).get("id", ""))["result"]
    sp_storage = {s["name"] for s in sp.get("eligibleStorageConditions", [])}
    ok = sp_target.get("value") == 1500.0 and sp_storage == {"Fridge"} and sp.get("eligibleWhenSealed") is True
    print(f"    [{'OK' if ok else 'FAIL'}] StockPolicy: target=1500g, eligible storage={{Fridge}}, "
          f"sealed-only")
    all_ok &= ok

    nt = client.get_all("NutritionTarget", nutrition_target_id)["result"]
    nt_range = client.get_all("QuantitySpecification", (nt.get("hasTargetRange") or {}).get("id", ""))["result"]
    ok = nt_range.get("minValue") == 50.0 and nt_range.get("maxValue") == 80.0 and nt.get("hasTimeScope") == "daily"
    print(f"    [{'OK' if ok else 'FAIL'}] NutritionTarget: range 50-80g, daily -- "
          f"min={nt_range.get('minValue')} max={nt_range.get('maxValue')}")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Meal-planning structural layer complete and verified: "
          "a real MealPlan with entries referencing real recipes, and BOTH kinds of "
          "PlanningConstraint attached through one polymorphic relationship.")


if __name__ == "__main__":
    main()
