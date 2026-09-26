"""Real on-hand inventory (near-expiry, already-expired, and sufficient
cases together) plus a real StockPolicy/NutritionTarget, then a full
selector run across the realistic dataset.

Numbered 17c, not 15f where it began, because it needs what 17a and 17b
create: the Opened/Sealed types and the compound-key shelf-life defaults
that mealplanner/inventory.py looks up to decide whether stock has expired.
Run in the old numeric position on a fresh instance it crashed on the
missing "Sealed" type. It also has to run BEFORE the 17d/18b demos, which add
more chicken stock and would break the exact totals checked below.

Run with: python3 scripts/17c_stock_and_selector_run.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.inventory import eligible_on_hand_with_urgency, physical_on_hand

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name):
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def build_portion(client, food_type, label, value_g, observed_days_ago, now, perishability=None):
    portion_id = client.upsert("PortionOfSubstance", "name", f"{P}{label}", {
        "instanceOf": dt(client, food_type),
        **({"hasPerishabilityType": dt(client, perishability)} if perishability else {}),
    })
    quality_id = client.upsert("Quality", "name", f"{P}{label} mass Quality", {
        "hasKind": dt(client, "Mass"), "inheresIn": portion_id,
    })
    when = now - timedelta(days=observed_days_ago)
    client.upsert("Measurement", "name", f"{P}{label} mass observation", {
        "value": value_g, "unit": "g", "status": "observed", "hasTime": when.strftime(FMT), "isAboutQuality": quality_id,
    })
    return portion_id


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    print("[1] Real on-hand inventory (near-expiry, already-expired, sufficient)...")
    build_portion(client, "Chicken Breast (raw)", "on-hand chicken -- near expiry", 600.0, 4, now, "Fresh Meat")  # 5-day shelf life, 1 day left
    build_portion(client, "Chicken Breast (raw)", "on-hand chicken -- already expired", 150.0, 8, now, "Fresh Meat")  # past 5-day shelf life
    build_portion(client, "Beef (raw)", "on-hand beef -- sufficient", 450.0, 1, now, "Fresh Meat")
    build_portion(client, "Broccoli", "on-hand broccoli -- sufficient", 350.0, 1, now)
    print("    built 4 on-hand portions")

    print("\n[2] Expiry verification...")
    cbr = dt(client, "Chicken Breast (raw)")
    eligible, urgency = eligible_on_hand_with_urgency(client, cbr, now)
    physical = physical_on_hand(client, cbr, now)
    print(f"    Chicken Breast (raw): physical={physical}g (should include both, 750g), "
          f"eligible={eligible}g (should exclude the expired 150g, ~600g), "
          f"soonest expiry={urgency:.2f}d")
    ok = abs(physical - 750.0) < 1 and abs(eligible - 600.0) < 1
    print(f"    [{'OK' if ok else 'FAIL'}]")
    if not ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\n[3] Real StockPolicy + NutritionTarget...")
    reorder_qty = client.upsert("QuantitySpecification", "name", f"{P}chicken reorder threshold -- 300g", {
        "value": 300.0, "unit": "g", "status": "specified",
    })
    target_qty = client.upsert("QuantitySpecification", "name", f"{P}chicken target level -- 1000g", {
        "value": 1000.0, "unit": "g", "status": "specified",
    })
    stock_policy_id = client.upsert("StockPolicy", "name", f"{P}Keep chicken breast on hand", {
        "appliesTo": dt(client, "Chicken Breast (raw)"), "hasReorderThreshold": reorder_qty, "hasTargetLevel": target_qty,
        "includesSubtypes": True, "eligibleStorageConditions": [dt(client, "Fridge")],
        "eligibleWhenOpened": False, "eligibleWhenSealed": True, "strictness": "soft", "weight": 0.3,
    })
    protein_range = client.upsert("QuantitySpecification", "name", f"{P}daily protein target range -- 50 to 80g", {
        "minValue": 50.0, "maxValue": 80.0, "unit": "g", "status": "specified",
    })
    nutrition_target_id = client.upsert("NutritionTarget", "name", f"{P}Daily protein target", {
        "forNutrient": dt(client, "Protein"), "hasTargetRange": protein_range,
        "hasTimeScope": "daily", "dayBoundaryRule": "midnight", "strictness": "soft", "weight": 0.4,
    })
    print(f"    stock_policy={stock_policy_id}  nutrition_target={nutrition_target_id}")

    print("\n[4] Real MealPlan, weighted for a Tuesday dinner decision...")
    meal_plan_id = client.upsert("MealPlan", "name", f"{P}Selector run week", {
        "timeBudgetMinutes": 60.0, "timeBudgetWeight": 0.3, "varietyWeight": 0.2,
        "stockWeight": 0.3, "wasteWeight": 0.3,
    })
    week_region = client.upsert("TemporalRegion", "name", f"{P}Selector run week temporal region", {
        "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(days=7)).strftime(FMT),
    })
    client.patch(f"/structr/rest/MealPlan/{meal_plan_id}", {
        "isAbout": week_region, "hasConstraint": [stock_policy_id, nutrition_target_id],
    })
    print(f"    meal_plan={meal_plan_id}")

    # The plan scripts/11c_simple_selector.py's own demo reads. 11c creates it
    # on first run, but on a fresh build 11c runs long before the realistic
    # recipes exist (and 15a wipes what it made), so it was only ever present
    # on the live instance because someone re-ran 11c by hand afterwards.
    demo_week = client.upsert("MealPlan", "name", f"{P}Selector demo week", {
        "timeBudgetMinutes": 30.0, "timeBudgetWeight": 0.8, "varietyWeight": 0.2,
    })
    print(f"    demo week for 11c={demo_week}")

    print("\n[5] Running the selector...")
    import importlib.util
    spec = importlib.util.spec_from_file_location("selector", os.path.join(os.path.dirname(__file__), "11c_simple_selector.py"))
    selector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector)

    for meal_type in [None, "Dinner"]:
        label = meal_type or "(unfiltered)"
        print(f"\n  --- meal_type={label} ---")
        ranked = selector.select(client, meal_plan_id, now, meal_type=meal_type)
        for r in ranked:
            name = r["plan"]["name"]
            if r["disqualified"]:
                print(f"    DISQUALIFIED  {name:50s}  {r['reason']}")
            else:
                print(f"    score={r['score']:.3f}  {name:50s}  {r['reason']}")
        winner = next((r for r in ranked if not r["disqualified"]), None)
        if winner:
            print(f"    Winner: {winner['plan']['name']} (score={winner['score']:.3f})")


if __name__ == "__main__":
    main()
