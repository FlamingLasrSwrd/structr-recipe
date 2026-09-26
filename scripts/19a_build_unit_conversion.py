"""Builds mealplanner/unit_conversion.py's supporting vocabulary
(Density/MassPerUnit DefaultSpecifications) and verifies the engine
against it -- fixes the "unit-blind" stock-scoring gap found by
external review of scripts/11c_simple_selector.py.

No SchemaNode/SchemaProperty/SchemaRelationshipNode changes here: the
`unit` field on QuantitySpecification and the Density/MassPerUnit
Default-Kind types already existed (mealplanner/metamodel_types.py,
mealplanner/seed_vocabulary.py). This is data seeding plus an engine
module, not a schema change -- no container restart needed.

Run with: python3 scripts/19a_build_unit_conversion.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.seed_vocabulary import (
    UNIT_CONVERSION_DOMAIN_TYPES,
    DENSITY_DEFAULT,
    MASS_PER_UNIT_DEFAULT,
)
from mealplanner.unit_conversion import convert_to_grams

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def build_default_spec(client, spec: dict, hierarchy_id: str) -> tuple[str, str]:
    for_type_id = client.upsert(
        "DomainType", "name", spec["for_type"], {"hierarchy": hierarchy_id, "isLookupBearing": True}
    )
    qty = spec["value"]
    qty_id = client.upsert(
        "QuantitySpecification", "name", qty["name"],
        {"value": qty["value"], "unit": qty["unit"], "status": qty["status"]},
    )
    kind_id = client.get("/structr/rest/DomainType", params={"name": spec["has_kind"]})["result"][0]["id"]
    default_spec_id = client.upsert(
        "DefaultSpecification", "name", spec["name"],
        {"forType": for_type_id, "hasKind": kind_id, "hasValue": qty_id},
    )
    return for_type_id, default_spec_id


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    food_identity_id = client.get(
        "/structr/rest/TypeHierarchy", params={"name": "Food Identity"}
    )["result"][0]["id"]

    print(f"[1] Creating {len(UNIT_CONVERSION_DOMAIN_TYPES)} DomainType(s)...")
    for name, hierarchy_name, parent_name, is_lookup_bearing in UNIT_CONVERSION_DOMAIN_TYPES:
        node_id = client.upsert(
            "DomainType", "name", name, {"hierarchy": food_identity_id, "isLookupBearing": is_lookup_bearing}
        )
        print(f"    {name}: {node_id}")

    print("\n[2] Creating Density default (AP Flour)...")
    flour_id, flour_spec_id = build_default_spec(client, DENSITY_DEFAULT, food_identity_id)
    print(f"    AP Flour={flour_id}  DefaultSpecification={flour_spec_id}")

    print("\n[3] Creating MassPerUnit default (Yellow Onion)...")
    onion_id, onion_spec_id = build_default_spec(client, MASS_PER_UNIT_DEFAULT, food_identity_id)
    print(f"    Yellow Onion={onion_id}  DefaultSpecification={onion_spec_id}")

    print("\n[4] Verifying convert_to_grams()...")
    all_ok = True
    cases = [
        ("AP Flour (2 cup)", flour_id, 2.0, "cup", 2.0 * 236.588 * 0.59),
        ("AP Flour (240 g, passthrough)", flour_id, 240.0, "g", 240.0),
        ("Yellow Onion (3 whole)", onion_id, 3.0, "whole", 3.0 * 180.0),
        ("Yellow Onion (unrecognized unit)", onion_id, 1.0, "bushel", None),
        ("AP Flour (2 each, no MassPerUnit default exists for it)", flour_id, 2.0, "each", None),
    ]
    for label, type_id, value, unit, expected in cases:
        actual = convert_to_grams(client, type_id, value, unit)
        if expected is None:
            ok = actual is None
            print(f"    [{'OK' if ok else 'FAIL'}] {label}: {value} {unit} -> {actual} (expected unconvertible/None)")
        else:
            ok = actual is not None and abs(actual - expected) < 0.01
            print(f"    [{'OK' if ok else 'FAIL'}] {label}: {value} {unit} -> {actual:.2f}g (expected {expected:.2f}g)")
        all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Unit-conversion engine built and verified.")


if __name__ == "__main__":
    main()
