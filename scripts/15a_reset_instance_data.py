"""Resets all instance-level content (recipes, inventory, cooks, meal
plans, stock/nutrition policies) for a clean full-lifecycle test pass.
Keeps the structural schema (untouched) and curated REAL vocabulary
(DomainType/TypeHierarchy/Concept) -- deletes TEST-prefixed vocabulary
entries too, for a genuine clean slate.

Everything deleted here is reconstructible from the committed scripts
(05, 06b/c/d, 08, 09, 10c, 11b, 12b, 13b, 14a) if needed.

Run with: python3 scripts/15a_reset_instance_data.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect


# Deleted unconditionally, all instances -- these are always "content",
# never vocabulary.
CONTENT_TYPES = [
    "MealPlanEntry", "MealPlan", "AcquisitionList",
    "StockPolicy", "NutritionTarget", "ExclusionConstraint",
    "Allocation", "Process", "TemporalRegion",
    "Measurement", "Quality", "Disposition", "Function", "Role",
    "PortionOfSubstance", "DiscreteWholeItem", "ContainerObject", "EquipmentObject",
    "StateRequirement", "Specification", "Step", "Plan", "RecipeIdentity",
]

# Vocabulary types: delete only TEST-prefixed entries, keep the rest.
VOCAB_TYPES = ["DomainType", "TypeHierarchy", "Concept", "ConceptScheme"]


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] Determining which QuantitySpecifications are vocabulary "
          "(referenced by a DefaultSpecification.hasValue) vs content...")
    default_specs = client.get_all("DefaultSpecification")["result"]
    keep_qty_ids = {ds["hasValue"]["id"] for ds in default_specs if ds.get("hasValue")}
    print(f"    {len(keep_qty_ids)} QuantitySpecifications kept as vocabulary "
          f"(NutrientProfile has no QuantitySpecification dependency)")

    print("\n[2] Deleting content types...")
    for type_name in CONTENT_TYPES:
        instances = client.get_all(type_name)["result"]
        for inst in instances:
            client.delete(f"/structr/rest/{type_name}/{inst['id']}")
        print(f"    {type_name}: deleted {len(instances)}")

    print("\n[3] Deleting non-vocabulary QuantitySpecifications...")
    all_qty = client.get_all("QuantitySpecification")["result"]
    deleted = 0
    for qty in all_qty:
        if qty["id"] not in keep_qty_ids:
            client.delete(f"/structr/rest/QuantitySpecification/{qty['id']}")
            deleted += 1
    print(f"    deleted {deleted}, kept {len(all_qty) - deleted}")

    print("\n[4] Deleting TEST-prefixed vocabulary...")
    for type_name in VOCAB_TYPES:
        instances = client.get_all(type_name)["result"]
        test_instances = [i for i in instances if i.get("name", "").startswith("TEST -- ")]
        for inst in test_instances:
            client.delete(f"/structr/rest/{type_name}/{inst['id']}")
        print(f"    {type_name}: deleted {len(test_instances)} TEST-prefixed, "
              f"kept {len(instances) - len(test_instances)}")

    print("\n[5] Also deleting DefaultSpecifications orphaned by the TEST-vocabulary "
          "deletion above...")
    # A deleted DomainType doesn't leave a stale/dangling id behind on
    # the relationship -- it leaves it simply empty (None). The first
    # version of this check looked for a stale id and missed every
    # already-nulled case, silently leaving 4 orphaned
    # DefaultSpecifications behind on first use. Check for missing
    # forType/hasKind directly instead.
    remaining_ds = client.get_all("DefaultSpecification")["result"]
    orphaned = 0
    for ds in remaining_ds:
        if not ds.get("forType") or not ds.get("hasKind"):
            if ds.get("hasValue"):
                client.delete(f"/structr/rest/QuantitySpecification/{ds['hasValue']['id']}")
            client.delete(f"/structr/rest/DefaultSpecification/{ds['id']}")
            orphaned += 1
    print(f"    removed {orphaned} orphaned DefaultSpecifications")

    print("\n[6] Final state...")
    for type_name in CONTENT_TYPES + ["QuantitySpecification"] + VOCAB_TYPES + ["DefaultSpecification"]:
        count = client.get_all(type_name)["result"]
        print(f"    {type_name}: {len(count)} remaining")


if __name__ == "__main__":
    main()
