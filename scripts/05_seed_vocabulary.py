"""Build order step 5: seed vocabulary (starting set).

Bare-minimum vocabulary for one recipe (the model's own braised-chicken
worked example). See mealplanner/seed_vocabulary.py for scope notes and
the multi-hierarchy resolution this builds on.

Run with: python3 scripts/05_seed_vocabulary.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.seed_vocabulary import HIERARCHIES, DOMAIN_TYPES, YIELD_DEFAULT

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print(f"[1] Creating {len(HIERARCHIES)} TypeHierarchies...")
    hierarchy_ids: dict[str, str] = {}
    for name, single_parent in HIERARCHIES:
        hierarchy_ids[name] = client.upsert(
            "TypeHierarchy", "name", name, {"singleParent": single_parent}
        )
        print(f"    {name}: {hierarchy_ids[name]}")

    print(f"\n[2] Creating {len(DOMAIN_TYPES)} DomainTypes (parents first, "
          "table is already in that order)...")
    domain_type_ids: dict[str, str] = {}
    for name, hierarchy_name, parent_name, is_lookup_bearing in DOMAIN_TYPES:
        fields = {
            "hierarchy": hierarchy_ids[hierarchy_name],
            "isLookupBearing": is_lookup_bearing,
        }
        if parent_name is not None:
            fields["parent"] = domain_type_ids[parent_name]
        domain_type_ids[name] = client.upsert("DomainType", "name", name, fields)
        parent_note = f" (parent={parent_name})" if parent_name else " (root)"
        print(f"    {name} [{hierarchy_name}]{parent_note}: {domain_type_ids[name]}")

    print("\n[3] Creating the yield DefaultSpecification...")
    qty = YIELD_DEFAULT["value"]
    qty_id = client.upsert(
        "QuantitySpecification", "name", qty["name"],
        {"value": qty["value"], "unit": qty["unit"], "status": qty["status"]},
    )
    default_spec_id = client.upsert(
        "DefaultSpecification", "name", YIELD_DEFAULT["name"],
        {
            "forType": domain_type_ids[YIELD_DEFAULT["for_type"]],
            "hasKind": domain_type_ids[YIELD_DEFAULT["has_kind"]],
            "keyedBy": [domain_type_ids[k] for k in YIELD_DEFAULT["keyed_by"]],
            "targetType": domain_type_ids[YIELD_DEFAULT["target_type"]],
            "hasValue": qty_id,
        },
    )
    print(f"    QuantitySpecification: {qty_id}")
    print(f"    DefaultSpecification:  {default_spec_id}")

    print("\n[4] Verification...")
    all_ok = True

    cb_raw = client.get_all("DomainType", domain_type_ids["Chicken Breast (raw)"])["result"]
    ok = (cb_raw.get("parent") or {}).get("id") == domain_type_ids["Poultry"]
    print(f"    [{'OK' if ok else 'FAIL'}] Chicken Breast (raw).parent -> Poultry")
    all_ok &= ok

    ds = client.get_all("DefaultSpecification", default_spec_id)["result"]
    ok = (
        (ds.get("forType") or {}).get("id") == domain_type_ids["Chicken Breast (raw)"]
        and (ds.get("hasKind") or {}).get("id") == domain_type_ids["Yield"]
        and (ds.get("targetType") or {}).get("id") == domain_type_ids["Chicken Breast (braised)"]
        and [k["id"] for k in ds.get("keyedBy", [])] == [domain_type_ids["Braising"]]
    )
    print(f"    [{'OK' if ok else 'FAIL'}] DefaultSpecification forType/hasKind/targetType/keyedBy all correct")
    all_ok &= ok

    print("\n[5] End-to-end: calling resolveDefault(Yield) on Chicken Breast (raw)...")
    result = client.call_method(
        "DomainType",
        domain_type_ids["Chicken Breast (raw)"],
        "resolveDefault",
        {"kindId": domain_type_ids["Yield"]},
    )
    ok = isinstance(result, dict) and result.get("id") == qty_id
    print(f"    [{'OK' if ok else 'FAIL'}] resolveDefault -> {result}")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Starting vocabulary seeded and functional.")
    print("\nIDs for reference:")
    for name, node_id in domain_type_ids.items():
        print(f"  {name}: {node_id}")


if __name__ == "__main__":
    main()
