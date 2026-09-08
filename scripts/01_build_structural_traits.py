"""Build order step 1: structural traits only, top-down, no properties.

Creates all types in mealplanner.structural_types.STRUCTURAL_TYPES via
ensure_type (idempotent -- safe to re-run), then verifies a real
multi-level chain reads back with the correct `inheritedTraits` on
EVERY link, reading the literal value rather than inferring from `name`
appearing (per CLAUDE.md / cheatsheet: a built-in `name` field shows up
regardless of whether the trait chain is actually wired).

Run with: python3 scripts/01_build_structural_traits.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.structural_types import STRUCTURAL_TYPES

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

# A real 7-level concrete chain from the tree, deliberately including
# the BfoObject rename point and ending at a concrete leaf that step 2
# will actually use as a polymorphic Allocation target.
CHAIN_TO_VERIFY = [
    "Entity",
    "Continuant",
    "IndependentContinuant",
    "MaterialEntity",
    "BfoObject",
    "FoodObject",
    "PortionOfSubstance",
]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print(f"[1] Creating {len(STRUCTURAL_TYPES)} structural types (idempotent)...")
    created_count = 0
    existing_count = 0
    name_to_id: dict[str, str] = {}
    for name, is_abstract, parent in STRUCTURAL_TYPES:
        inherited = [parent] if parent else None
        node_id, created = client.ensure_type(name, is_abstract=is_abstract, inherited_traits=inherited)
        name_to_id[name] = node_id
        if created:
            created_count += 1
        else:
            existing_count += 1
    print(f"    {created_count} created, {existing_count} already existed")

    print(f"\n[2] Verifying inheritedTraits on every link of the chain:")
    print(f"    {' -> '.join(CHAIN_TO_VERIFY)}")
    all_ok = True
    for i in range(1, len(CHAIN_TO_VERIFY)):
        child = CHAIN_TO_VERIFY[i]
        expected_parent = CHAIN_TO_VERIFY[i - 1]
        node = client.get("/structr/rest/SchemaNode", params={"name": child})["result"][0]
        actual_traits = node.get("inheritedTraits") or []
        ok = expected_parent in actual_traits
        status = "OK" if ok else "FAIL"
        print(f"    [{status}] {child}.inheritedTraits = {actual_traits} "
              f"(expected to contain {expected_parent!r})")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nFAILED: at least one link in the chain does not have the "
              "expected inheritedTraits value. Per the build order, stop "
              "here rather than proceeding to step 2.")
        sys.exit(1)

    print("\n[3] Spot-check: does a leaf type's schema-node /all view show "
          "the full inherited property set behaving as real inheritance, "
          "not just metadata? (No custom properties exist yet in step 1 -- "
          "this just confirms the SchemaNode record itself is well-formed.)")
    leaf = client.get("/structr/rest/SchemaNode", params={"name": "PortionOfSubstance"})["result"][0]
    print(f"    PortionOfSubstance: isAbstract={leaf.get('isAbstract')}, "
          f"inheritedTraits={leaf.get('inheritedTraits')}")

    print("\nAll checks passed. Structural trait layer built and verified.")


if __name__ == "__main__":
    main()
