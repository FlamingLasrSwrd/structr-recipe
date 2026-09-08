"""NutrientProfiles for the two new recipe outputs (needed for nutrition
scoring to see them at all), plus rebuilding the allergy-exclusion
scenario (Almonds/Tree Nut) in the fresh dataset -- the original was
deleted in the reset.

Run with: python3 scripts/15d_nutrient_profiles_and_exclusion.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "
PLACEHOLDER_NOTE = "[PLACEHOLDER -- not sourced from USDA/FDC yet]"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] NutrientProfiles for the two new outputs...")
    protein = dt(client, "Protein")
    pasta_profile = client.upsert(
        "NutrientProfile", "name", f"Buttered Pasta with Parmesan protein profile {PLACEHOLDER_NOTE}",
        {"isAbout": dt(client, "Buttered Pasta with Parmesan"), "forNutrient": protein, "amount": 9.0, "basis": "per_100g"},
    )
    stirfry_profile = client.upsert(
        "NutrientProfile", "name", f"Beef and Broccoli Stir-Fry protein profile {PLACEHOLDER_NOTE}",
        {"isAbout": dt(client, "Beef and Broccoli Stir-Fry"), "forNutrient": protein, "amount": 20.0, "basis": "per_100g"},
    )
    print(f"    pasta={pasta_profile}  stirfry={stirfry_profile}")

    print("\n[2] Allergy exclusion scenario: Almonds (Tree Nut) + a trivial "
          "recipe using them...")
    almonds = client.upsert("DomainType", "name", "Almonds", {
        "isLookupBearing": True,
        "hierarchy": client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"],
    })
    client.patch(f"/structr/rest/DomainType/{almonds}", {"hasBiologicalOrigin": [dt(client, "Tree Nut")]})

    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}Almond Snack Mix", {
        "isRetired": False,
        "hasMealType": [client.get("/structr/rest/Concept", params={"name": "Snack"})["result"][0]["id"]],
    })
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for Almond Snack Mix", {
        "value": 1.0, "unit": "batch", "status": "specified",
    })
    plan_id = client.upsert("Plan", "name", f"{P}Almond Snack Mix v1", {
        "specializationOf": recipe_id, "hasRecipeYield": yield_qty,
        "estimatedDurationMinutes": 2.0, "difficultyRating": "easy",
    })
    # A trivial "no transformation" step -- reuse Boiling's structural
    # slot loosely isn't right; there's no real "Assembly"/"No-Cook"
    # Transformation Method in the vocabulary. Using it anyway would be
    # wrong. This is itself a finding (see the write-up) -- worked
    # around here by just not giving the Step an instance_of, which the
    # schema permits (it's not notNull) but which is honestly a gap.
    step_id = client.upsert("Step", "name", f"{P}Portion the almond snack mix", {"plan": plan_id})
    almond_qty = client.upsert("QuantitySpecification", "name", f"{P}almond snack mix quantity", {
        "value": 100.0, "unit": "g", "status": "specified",
    })
    client.upsert("Specification", "name", f"{P}almond snack S1 input almonds", {
        "step": step_id, "hasParticipationRole": "input", "specifies": almonds,
        "hasSpecifiedQuantity": almond_qty, "isOptional": False,
    })
    out_qty = client.upsert("QuantitySpecification", "name", f"{P}almond snack output quantity", {
        "value": 100.0, "unit": "g", "status": "specified",
    })
    client.upsert("Specification", "name", f"{P}almond snack output", {
        "step": step_id, "hasParticipationRole": "output", "specifies": almonds,
        "hasSpecifiedQuantity": out_qty, "isOptional": False,
    })

    exclusion_id = client.upsert("ExclusionConstraint", "name", f"{P}Tree nut allergy exclusion", {
        "appliesTo": dt(client, "Tree Nut"), "strictness": "hard",
    })
    print(f"    almonds={almonds} recipe={recipe_id} exclusion={exclusion_id}")

    print("\n[3] Verification...")
    almonds_full = client.get_all("DomainType", almonds)["result"]
    origins = {o["name"] for o in almonds_full.get("hasBiologicalOrigin", [])}
    ok = origins == {"Tree Nut"}
    print(f"    [{'OK' if ok else 'FAIL'}] Almonds.hasBiologicalOrigin -> {origins}")
    if not ok:
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
