"""Seed real NutrientProfile data for the cooked outputs already in the
recipe library, so planning-time nutrition scoring has something to
read. Values are PLACEHOLDER (roughly plausible, not FDC-sourced),
flagged the same way the yield factor was back in step 5.

Also attaches the existing "Daily protein target" NutritionTarget to
the selector's demo MealPlan via hasConstraint -- it was built in step
6's session but never actually wired to the MealPlan the selector reads
from.

Run with: python3 scripts/12b_seed_nutrient_profiles.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
PLACEHOLDER_NOTE = "[PLACEHOLDER -- not sourced from USDA/FDC yet]"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] NutrientProfile: Chicken Breast (braised), protein, ~31g/100g...")
    protein = dt(client, "Protein")
    chicken_profile = client.upsert(
        "NutrientProfile", "name", f"Chicken Breast (braised) protein profile {PLACEHOLDER_NOTE}",
        {"isAbout": dt(client, "Chicken Breast (braised)"), "forNutrient": protein, "amount": 31.0, "basis": "per_100g"},
    )
    print(f"    {chicken_profile}")

    print("\n[2] NutrientProfile: Pasta (cooked), protein, ~5g/100g...")
    pasta_profile = client.upsert(
        "NutrientProfile", "name", f"TEST -- Pasta (cooked) protein profile {PLACEHOLDER_NOTE}",
        {"isAbout": dt(client, "TEST -- Pasta (cooked)"), "forNutrient": protein, "amount": 5.0, "basis": "per_100g"},
    )
    print(f"    {pasta_profile}")

    print("\n[3] Attaching the real 'Daily protein target' NutritionTarget to the "
          "selector's demo MealPlan...")
    nutrition_target = client.get("/structr/rest/NutritionTarget", params={"name": "TEST -- Daily protein target"})["result"][0]["id"]
    meal_plan = client.get("/structr/rest/MealPlan", params={"name": "TEST -- Selector demo week"})["result"][0]["id"]
    existing_constraints = [c["id"] for c in client.get_all("MealPlan", meal_plan)["result"].get("hasConstraint", [])]
    if nutrition_target not in existing_constraints:
        client.patch(f"/structr/rest/MealPlan/{meal_plan}", {"hasConstraint": existing_constraints + [nutrition_target]})
    print(f"    meal_plan={meal_plan} now has NutritionTarget={nutrition_target} attached")

    print("\n[4] Verification...")
    cp = client.get_all("NutrientProfile", chicken_profile)["result"]
    pp = client.get_all("NutrientProfile", pasta_profile)["result"]
    ok = (
        cp.get("amount") == 31.0 and (cp.get("isAbout") or {}).get("name") == "Chicken Breast (braised)"
        and pp.get("amount") == 5.0 and (pp.get("isAbout") or {}).get("name") == "TEST -- Pasta (cooked)"
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Both profiles read back correctly")
    mp = client.get_all("MealPlan", meal_plan)["result"]
    constraint_types = {c["id"]: c["type"] for c in mp.get("hasConstraint", [])}
    ok2 = constraint_types.get(nutrition_target) == "NutritionTarget"
    print(f"    [{'OK' if ok2 else 'FAIL'}] MealPlan.hasConstraint includes the NutritionTarget")

    if not (ok and ok2):
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
