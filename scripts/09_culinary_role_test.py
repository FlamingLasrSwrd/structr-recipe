"""Breadth test, part 2: Culinary Role substitution (data-model.md
Sec 5.3) -- structural proof, not a full recipe.

Demonstrates:
  - `may_bear_role`: Butter and Margarine (far apart in Food Identity --
    dairy vs. plant fat) both may_bear_role "Baking Fat" (close together
    in Culinary Role) -- the whole reason the hierarchy split exists.
  - F11: a Specification's `specifies` naming a Culinary Role directly
    ("any baking fat") instead of a specific food, for a recipe that
    genuinely doesn't care which fat is used.

Similarity computation itself (walking may_bear_role at query time) is
application logic, out of scope for a structural test -- this proves
the DATA SHAPE the computation would walk, not the computation.

Run with: python3 scripts/09_culinary_role_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.breadth_test import P, CULINARY_ROLE_HIERARCHY

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Culinary Role hierarchy + Baking Fat type...")
    role_hier = client.upsert("TypeHierarchy", "name", CULINARY_ROLE_HIERARCHY, {"singleParent": True})
    baking_fat = client.upsert("DomainType", "name", f"{P}Baking Fat", {"isLookupBearing": True, "hierarchy": role_hier})
    print(f"    hierarchy={role_hier}  Baking Fat={baking_fat}")

    print("\n[2] Food-Identity types Butter and Margarine (far apart in Food "
          "Identity -- dairy vs. plant fat)...")
    food_identity_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
    butter = client.upsert("DomainType", "name", f"{P}Butter", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    margarine = client.upsert("DomainType", "name", f"{P}Margarine", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    print(f"    Butter={butter}  Margarine={margarine}")

    print("\n[3] may_bear_role: both -> Baking Fat (close together in "
          "Culinary Role, per Sec 5.3's own example)...")
    client.patch(f"/structr/rest/DomainType/{butter}", {"mayBearRole": [baking_fat]})
    client.patch(f"/structr/rest/DomainType/{margarine}", {"mayBearRole": [baking_fat]})

    baking_fat_full = client.get_all("DomainType", baking_fat)["result"]
    bearers = {b["id"] for b in baking_fat_full.get("canBeBorneBy", [])}
    ok = bearers == {butter, margarine}
    print(f"    [{'OK' if ok else 'FAIL'}] Baking Fat.canBeBorneBy (reverse of may_bear_role) "
          f"= {{Butter, Margarine}}: {ok}")
    assert ok

    print("\n[4] F11: a Specification whose `specifies` names the Culinary "
          "Role directly -- 'any baking fat', not a specific food...")
    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}Simple Saute", {"isRetired": False})
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for Simple Saute", {"value": 1.0, "unit": "batch", "status": "specified"})
    plan_id = client.upsert("Plan", "name", f"{P}Simple Saute v1", {"specializationOf": recipe_id, "hasRecipeYield": yield_qty})
    # No specific Transformation Method vocabulary needed for this
    # structural proof -- reuse the real "Braising" kind loosely as a
    # stand-in step classification; the point under test is `specifies`,
    # not the transformation method.
    step_id = client.upsert("Step", "name", f"{P}Saute step", {
        "plan": plan_id,
        "instanceOf": client.get("/structr/rest/DomainType", params={"name": "Braising"})["result"][0]["id"],
    })
    fat_qty = client.upsert("QuantitySpecification", "name", f"{P}saute fat quantity -- 1 tbsp", {"value": 1.0, "unit": "tbsp", "status": "specified"})
    s_fat_id = client.upsert("Specification", "name", f"{P}saute S1 input any baking fat", {
        "step": step_id, "hasParticipationRole": "input",
        "specifies": baking_fat,  # <- the Culinary Role type directly, not Butter or Margarine
        "hasSpecifiedQuantity": fat_qty, "isOptional": False,
    })
    spec = client.get_all("Specification", s_fat_id)["result"]
    ok = (spec.get("specifies") or {}).get("id") == baking_fat and (spec.get("specifies") or {}).get("name") == f"{P}Baking Fat"
    print(f"    [{'OK' if ok else 'FAIL'}] Specification.specifies -> {spec.get('specifies')} "
          f"(a Culinary Role type, not a specific food)")
    assert ok

    print("\n[5] Confirming the walk a similarity computation WOULD do at "
          "query time (not implemented here -- just proving the data is "
          "shaped correctly for it): from the Role, both candidate foods "
          "are reachable...")
    print(f"    Baking Fat.canBeBorneBy -> {[b['name'] for b in baking_fat_full.get('canBeBorneBy', [])]}")

    print("\nAll checks passed. Culinary Role substitution mechanism (Sec 5.3) "
          "structurally proven: may_bear_role links food types to roles, and "
          "specifies can name a Role directly for an input slot.")


if __name__ == "__main__":
    main()
