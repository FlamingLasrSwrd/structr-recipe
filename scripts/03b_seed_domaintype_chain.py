"""Build order step 3, part B: a three-level DomainType chain, as data.

Everything created here is test/demo data for verifying resolveDefault,
NOT the real seed vocabulary (that's build order step 5 -- "real
curation work, not a formality," per CLAUDE.md). Every node is
name-prefixed "TEST -- " for exactly that reason.

Chain (mirrors data-model.md Sec 10's worked example):
    TEST -- Fresh Meat  (root of this test hierarchy)
      `- TEST -- Poultry               <- DefaultSpecification(Density) lives HERE
           `- TEST -- Chicken Breast (raw)   <- no default of its own; must walk up

Separately: TEST -- Density, a DomainType in its own "Default Kind"
hierarchy, used as the `hasKind` value.

Run with: python3 scripts/03b_seed_domaintype_chain.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

P = "TEST -- "  # test-data name prefix


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] TypeHierarchies...")
    food_identity_hier = client.upsert(
        "TypeHierarchy", "name", f"{P}Food Identity", {"singleParent": True}
    )
    default_kind_hier = client.upsert(
        "TypeHierarchy", "name", f"{P}Default Kind", {"singleParent": True}
    )
    print(f"    {P}Food Identity: {food_identity_hier}")
    print(f"    {P}Default Kind:  {default_kind_hier}")

    print("\n[2] Three-level DomainType chain in Food Identity...")
    fresh_meat = client.upsert(
        "DomainType", "name", f"{P}Fresh Meat",
        {"isLookupBearing": True, "hierarchy": food_identity_hier},
    )
    poultry = client.upsert(
        "DomainType", "name", f"{P}Poultry",
        {"isLookupBearing": True, "hierarchy": food_identity_hier, "parent": fresh_meat},
    )
    chicken_breast_raw = client.upsert(
        "DomainType", "name", f"{P}Chicken Breast (raw)",
        {"isLookupBearing": True, "hierarchy": food_identity_hier, "parent": poultry},
    )
    print(f"    {P}Fresh Meat:           {fresh_meat}  (root, no parent)")
    print(f"    {P}Poultry:              {poultry}  (parent=Fresh Meat)")
    print(f"    {P}Chicken Breast (raw): {chicken_breast_raw}  (parent=Poultry)")

    print("\n[3] Default-Kind DomainType (what a DefaultSpecification's hasKind points at)...")
    density_kind = client.upsert(
        "DomainType", "name", f"{P}Density",
        {"isLookupBearing": False, "hierarchy": default_kind_hier},
    )
    print(f"    {P}Density: {density_kind}")

    print("\n[4] QuantitySpecification (the default VALUE) + DefaultSpecification "
          "(attached to Poultry, NOT to Chicken Breast (raw) -- forces resolveDefault "
          "to actually walk up one level)...")
    qty_spec = client.upsert(
        "QuantitySpecification", "name", f"{P}density value for Poultry default",
        {"value": 1.05, "unit": "g/mL", "status": "default"},
    )
    default_spec = client.upsert(
        "DefaultSpecification", "name", f"{P}Poultry density default",
        {"hasKind": density_kind, "forType": poultry, "hasValue": qty_spec},
    )
    print(f"    QuantitySpecification:  {qty_spec}  (1.05 g/mL, status=default)")
    print(f"    DefaultSpecification:   {default_spec}  (forType=Poultry, hasKind=Density)")

    print("\n[5] Read-back verification of the chain structure...")
    cb = client.get_all("DomainType", chicken_breast_raw)["result"]
    po = client.get_all("DomainType", poultry)["result"]
    fm = client.get_all("DomainType", fresh_meat)["result"]

    ok = True
    ok &= (cb.get("parent") or {}).get("id") == poultry
    print(f"    [{'OK' if (cb.get('parent') or {}).get('id') == poultry else 'FAIL'}] "
          f"Chicken Breast (raw).parent -> {cb.get('parent')}")
    ok &= (po.get("parent") or {}).get("id") == fresh_meat
    print(f"    [{'OK' if (po.get('parent') or {}).get('id') == fresh_meat else 'FAIL'}] "
          f"Poultry.parent -> {po.get('parent')}")
    ok &= fm.get("parent") is None
    print(f"    [{'OK' if fm.get('parent') is None else 'FAIL'}] "
          f"Fresh Meat.parent -> {fm.get('parent')} (expected None -- hierarchy root)")

    ds = client.get_all("DefaultSpecification", default_spec)["result"]
    ok &= (ds.get("forType") or {}).get("id") == poultry
    ok &= (ds.get("hasKind") or {}).get("id") == density_kind
    ok &= (ds.get("hasValue") or {}).get("id") == qty_spec
    print(f"    [{'OK' if ok else 'FAIL'}] DefaultSpecification.forType/hasKind/hasValue "
          f"all resolve correctly")

    if not ok:
        print("\nFAILED -- chain or default-spec did not read back as expected.")
        sys.exit(1)

    print(f"\nData seeded and verified. IDs for the next script:")
    print(f"  fresh_meat={fresh_meat}")
    print(f"  poultry={poultry}")
    print(f"  chicken_breast_raw={chicken_breast_raw}")
    print(f"  density_kind={density_kind}")


if __name__ == "__main__":
    main()
