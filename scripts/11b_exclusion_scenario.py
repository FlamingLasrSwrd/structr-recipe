"""Builds the exclusion scenario: a nut-containing test recipe (plan
side only -- no inventory/execution needed, since planning-time
filtering only reads Specifications, not physical instances), tagged
via Biological Origin, plus a hard ExclusionConstraint that should
disqualify it from selection.

TEST-marked throughout -- illustrative, not a real user's allergy data.

Run with: python3 scripts/11b_exclusion_scenario.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Almonds (Food Identity), tagged with Biological Origin = Tree Nut...")
    food_identity_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
    xform_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Transformation Method"})["result"][0]["id"]

    almonds = client.upsert("DomainType", "name", f"{P}Almonds", {
        "isLookupBearing": True, "hierarchy": food_identity_hier,
        "hasBiologicalOrigin": [dt(client, "Tree Nut")],
    })
    no_cook = client.upsert("DomainType", "name", f"{P}No-Cook Assembly", {"isLookupBearing": True, "hierarchy": xform_hier})
    print(f"    Almonds={almonds}  No-Cook Assembly={no_cook}")

    print("\n[2] Minimal recipe: TEST -- Almond Snack (plan side only, no cook needed "
          "for planning-time filtering)...")
    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}Almond Snack", {"isRetired": False})
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for Almond Snack", {"value": 1.0, "unit": "batch", "status": "specified"})
    plan_id = client.upsert("Plan", "name", f"{P}Almond Snack v1", {
        "specializationOf": recipe_id, "hasRecipeYield": yield_qty,
        "estimatedDurationMinutes": 2.0, "difficultyRating": "easy",
    })
    step_id = client.upsert("Step", "name", f"{P}Assemble the almond snack", {"plan": plan_id, "instanceOf": no_cook})
    almond_qty = client.upsert("QuantitySpecification", "name", f"{P}almond snack input quantity -- 30g", {"value": 30.0, "unit": "g", "status": "specified"})
    s1_id = client.upsert("Specification", "name", f"{P}almond snack S1 input almonds", {
        "step": step_id, "hasParticipationRole": "input", "specifies": almonds,
        "hasSpecifiedQuantity": almond_qty, "isOptional": False,
    })
    print(f"    recipe={recipe_id} plan={plan_id} step={step_id} s1={s1_id}")

    print("\n[3] Hard ExclusionConstraint: no tree nuts...")
    exclusion_id = client.upsert("ExclusionConstraint", "name", f"{P}Tree nut allergy exclusion", {
        "appliesTo": dt(client, "Tree Nut"), "strictness": "hard",
    })
    print(f"    exclusion={exclusion_id}")

    print("\n[4] Verification...")
    all_ok = True

    almonds_full = client.get_all("DomainType", almonds)["result"]
    ok = {o["id"] for o in almonds_full.get("hasBiologicalOrigin", [])} == {dt(client, "Tree Nut")}
    print(f"    [{'OK' if ok else 'FAIL'}] Almonds.hasBiologicalOrigin -> Tree Nut")
    all_ok &= ok

    ec = client.get_all("ExclusionConstraint", exclusion_id)["result"]
    ok = (ec.get("appliesTo") or {}).get("name") == "Tree Nut" and ec.get("strictness") == "hard"
    print(f"    [{'OK' if ok else 'FAIL'}] ExclusionConstraint: appliesTo=Tree Nut, strictness=hard")
    all_ok &= ok

    s1 = client.get_all("Specification", s1_id)["result"]
    ok = (s1.get("specifies") or {}).get("id") == almonds
    print(f"    [{'OK' if ok else 'FAIL'}] Almond Snack's S1 specifies Almonds")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Exclusion scenario ready for the selector to filter against.")


if __name__ == "__main__":
    main()
