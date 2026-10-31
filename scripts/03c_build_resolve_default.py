"""Build order step 3, part C: a Type's default found by walking its parents.

Per structr-build-sketch.md Sec 5: resolving a default on a DomainType walks
SUBCLASS_OF* upward, nearest wins, and returns the QuantitySpecification or
nothing. This checks that walk on the three-level chain 03b built.

Until 2026-10-31 this script built it as a StructrScript SchemaMethod,
`resolveDefault`, the spike that proved the walk could run inside Structr.
StructrScript could not pass a value into a nested method call (recorded in
structr-cheatsheet.md Sec 3a), so the method unrolled the walk over a fixed
six levels, and it filtered only by kind, never by `keyedBy` (REVIEW.md round
2, #5). mealplanner/defaults.py has resolved by kind and keys, with no depth
limit, ever since, and every caller uses it, so the method was retired
(scripts/47a removes it from an instance built before). This script now runs
the same four cases through that resolver.

Run with: python3 scripts/03c_build_resolve_default.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.defaults import resolve_default


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] Resolving defaults on the test chain built in 03b "
          "(re-looking-up IDs by name, not hardcoded, since this script "
          "should be independently re-runnable)...")

    def domain_type_id(name: str) -> str:
        return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]

    poultry = domain_type_id("TEST -- Poultry")
    chicken = domain_type_id("TEST -- Chicken Breast (raw)")
    fresh_meat = domain_type_id("TEST -- Fresh Meat")
    density = domain_type_id("TEST -- Density")

    cases = [
        ("Poultry, own default (depth 0)", poultry, density, "TEST -- density value for Poultry default"),
        ("Chicken Breast (raw), walk up 1 level", chicken, density, "TEST -- density value for Poultry default"),
        ("Fresh Meat, root, no default above -> null", fresh_meat, density, None),
        ("Chicken Breast (raw), non-matching kind -> null", chicken, "nonexistent-id", None),
    ]

    all_ok = True
    for label, node_id, kind_id, expected_name in cases:
        resolved = resolve_default(client, node_id, kind_id)
        name = resolved.quantity.get("name") if resolved else None
        ok = name == expected_name
        all_ok &= ok
        print(f"    [{'OK' if ok else 'FAIL'}] {label} -> {name}")

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. The walk resolves as build-order step 3 requires.")


if __name__ == "__main__":
    main()
