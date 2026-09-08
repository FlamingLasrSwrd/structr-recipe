"""Build order step 2: one polymorphic target.

`Allocation -[ABOUT]-> Entity`, satisfied by both a PortionOfSubstance
and an EquipmentObject -- per structr-build-sketch.md Sec 8, this is
"the load-bearing assumption of the whole structural layer." If this
fails, the whole structural-layer approach needs rethinking; per
CLAUDE.md, do not proceed past a failure here.

Relationship shape taken directly from the build sketch's Sec 6 table:
    Allocation --ABOUT--> Entity
        targetJsonName (property on Allocation)  = "isAbout"
        sourceJsonName (property on Entity side) = "allocationsAbout"

Multiplicity note (learned the hard way on the first run of this
script): sourceMultiplicity/targetMultiplicity describe cardinality
per participant, not "how many on each side of the arrow" the way it
reads. One Allocation is about exactly one Entity (invariant 4), so
targetMultiplicity="1" (one target per source). Many Allocations can
be about the same Entity over time, so sourceMultiplicity="*" (many
sources per target). Getting this backwards makes `isAbout` come back
"expected a JSON collection" on write.

Test data convention: every instance created by this script is real
schema data (not a disposable probe type, unlike step 0), so it is
NOT deleted afterward -- it stays as a permanent, clearly-marked
example. Every such instance's `name` is prefixed "TEST -- " so a
later script or person querying real data never mistakes it for a
real portion/equipment/allocation.

Run with: python3 scripts/02_polymorphic_target.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

TEST_PREFIX = "TEST -- "


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Looking up Allocation and Entity SchemaNode ids...")
    allocation_type = client.get("/structr/rest/SchemaNode", params={"name": "Allocation"})["result"]
    entity_type = client.get("/structr/rest/SchemaNode", params={"name": "Entity"})["result"]
    if not allocation_type or not entity_type:
        print("FAILED: Allocation or Entity SchemaNode not found -- run "
              "scripts/01_build_structural_traits.py first.")
        sys.exit(1)
    allocation_id = allocation_type[0]["id"]
    entity_id = entity_type[0]["id"]
    print(f"    Allocation={allocation_id}  Entity={entity_id}")

    print("\n[2] Ensuring Allocation -[ABOUT]-> Entity relationship...")
    rel_id, created = client.ensure_relationship(
        source_id=allocation_id,
        target_id=entity_id,
        relationship_type="ABOUT",
        source_multiplicity="*",
        target_multiplicity="1",
        source_json_name="allocationsAbout",
        target_json_name="isAbout",
    )
    print(f"    relationship id={rel_id}, created={created}")

    print("\n[3] Creating one test PortionOfSubstance and one test EquipmentObject "
          "(both created AFTER the relationship exists, so the retroactive-labeling "
          "trap does not apply)...")
    portion = client.post(
        "/structr/rest/PortionOfSubstance",
        {
            "name": f"{TEST_PREFIX}polymorphic-target portion of substance",
            "visibleToAuthenticatedUsers": True,
        },
    )["result"][0]
    equipment = client.post(
        "/structr/rest/EquipmentObject",
        {
            "name": f"{TEST_PREFIX}polymorphic-target equipment object",
            "visibleToAuthenticatedUsers": True,
        },
    )["result"][0]
    print(f"    PortionOfSubstance id={portion}")
    print(f"    EquipmentObject id={equipment}")

    print("\n[4] Creating two test Allocations, each `isAbout` a different concrete type...")
    alloc_re_portion = client.post(
        "/structr/rest/Allocation",
        {
            "name": f"{TEST_PREFIX}allocation about a PortionOfSubstance",
            "isAbout": portion,
            "visibleToAuthenticatedUsers": True,
        },
    )["result"][0]
    alloc_re_equipment = client.post(
        "/structr/rest/Allocation",
        {
            "name": f"{TEST_PREFIX}allocation about an EquipmentObject",
            "isAbout": equipment,
            "visibleToAuthenticatedUsers": True,
        },
    )["result"][0]
    print(f"    Allocation(re: portion) id={alloc_re_portion}")
    print(f"    Allocation(re: equipment) id={alloc_re_equipment}")

    print("\n[5] Reading back both, from the Allocation side (isAbout) and the "
          "Entity side (allocationsAbout) -- confirming polymorphic targeting "
          "works in both directions for two different concrete subtypes...")

    all_ok = True

    a1 = client.get_all("Allocation", alloc_re_portion)["result"]
    ok1 = a1.get("isAbout", {}).get("id") == portion and a1["isAbout"]["type"] == "PortionOfSubstance"
    print(f"    [{'OK' if ok1 else 'FAIL'}] Allocation({alloc_re_portion}).isAbout -> "
          f"{a1.get('isAbout')}")
    all_ok &= ok1

    a2 = client.get_all("Allocation", alloc_re_equipment)["result"]
    ok2 = a2.get("isAbout", {}).get("id") == equipment and a2["isAbout"]["type"] == "EquipmentObject"
    print(f"    [{'OK' if ok2 else 'FAIL'}] Allocation({alloc_re_equipment}).isAbout -> "
          f"{a2.get('isAbout')}")
    all_ok &= ok2

    portion_readback = client.get_all("PortionOfSubstance", portion)["result"]
    portion_allocs = [x["id"] for x in portion_readback.get("allocationsAbout", [])]
    ok3 = alloc_re_portion in portion_allocs
    print(f"    [{'OK' if ok3 else 'FAIL'}] PortionOfSubstance({portion}).allocationsAbout -> "
          f"{portion_allocs}")
    all_ok &= ok3

    equipment_readback = client.get_all("EquipmentObject", equipment)["result"]
    equipment_allocs = [x["id"] for x in equipment_readback.get("allocationsAbout", [])]
    ok4 = alloc_re_equipment in equipment_allocs
    print(f"    [{'OK' if ok4 else 'FAIL'}] EquipmentObject({equipment}).allocationsAbout -> "
          f"{equipment_allocs}")
    all_ok &= ok4

    print("\n[6] Confirming via the generic Entity collection endpoint too "
          "(both instances should show up as Entity, since every concrete "
          "type inherits it)...")
    entity_collection = client.get("/structr/rest/Entity", params={"id": portion})["result"]
    ok5 = len(entity_collection) == 1
    print(f"    [{'OK' if ok5 else 'FAIL'}] GET /Entity?id={portion} -> "
          f"{len(entity_collection)} result(s)")
    all_ok &= ok5

    if not all_ok:
        print("\nFAILED: the polymorphic-target assumption did not hold. "
              "Per the build order, stop here -- this is the load-bearing "
              "assumption of the whole structural layer and needs rethinking "
              "before proceeding to step 3.")
        sys.exit(1)

    print("\nAll checks passed. Allocation -[ABOUT]-> Entity is genuinely "
          "polymorphic: satisfied by PortionOfSubstance and EquipmentObject "
          "through one shared declaration, in both directions.")
    print(f"\nTest data left in place (per convention, not deleted), all "
          f"name-prefixed {TEST_PREFIX!r}:")
    print(f"  PortionOfSubstance {portion}")
    print(f"  EquipmentObject    {equipment}")
    print(f"  Allocation         {alloc_re_portion}")
    print(f"  Allocation         {alloc_re_equipment}")


if __name__ == "__main__":
    main()
