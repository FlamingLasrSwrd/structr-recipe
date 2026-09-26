"""Seeds vocabulary for the realistic full-lifecycle test pass. See
mealplanner/seed_vocabulary.py's REALISTIC_PASS_* lists.

Run with: python3 scripts/15b_seed_realistic_vocab.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.seed_vocabulary import (
    PLACEHOLDER_NOTE, REALISTIC_PASS_HIERARCHIES, REALISTIC_PASS_DOMAIN_TYPES, REALISTIC_YIELD_DEFAULTS,
)


def main():
    client = connect()
    client.wait_until_ready()

    hierarchy_ids = {}
    for name, single_parent in REALISTIC_PASS_HIERARCHIES:
        hierarchy_ids[name] = client.upsert("TypeHierarchy", "name", name, {"singleParent": single_parent})
        print(f"hierarchy {name}: {hierarchy_ids[name]}")

    domain_type_ids = {}
    for name, hierarchy_name, parent_name, is_lookup_bearing in REALISTIC_PASS_DOMAIN_TYPES:
        hierarchy_id = hierarchy_ids.get(hierarchy_name) or client.get(
            "/structr/rest/TypeHierarchy", params={"name": hierarchy_name}
        )["result"][0]["id"]
        fields = {"hierarchy": hierarchy_id, "isLookupBearing": is_lookup_bearing}
        if parent_name is not None:
            fields["parent"] = domain_type_ids.get(parent_name) or client.get(
                "/structr/rest/DomainType", params={"name": parent_name}
            )["result"][0]["id"]
        domain_type_ids[name] = client.upsert("DomainType", "name", name, fields)
        print(f"domain type {name}: {domain_type_ids[name]}")

    print("\nYield defaults (per-ingredient, keyed by transformation)...")
    yield_kind = client.get("/structr/rest/DomainType", params={"name": "Yield"})["result"][0]["id"]
    for for_type, transformation, target, factor in REALISTIC_YIELD_DEFAULTS:
        value_id = client.upsert("QuantitySpecification", "name", f"{for_type} via {transformation} yield value {PLACEHOLDER_NOTE}", {
            "value": factor, "unit": "ratio", "status": "default",
        })
        fields = {
            "forType": domain_type_ids.get(for_type) or client.get("/structr/rest/DomainType", params={"name": for_type})["result"][0]["id"],
            "hasKind": yield_kind, "hasValue": value_id,
            "keyedBy": [domain_type_ids[transformation]],
        }
        if target:
            fields["targetType"] = domain_type_ids[target]
        spec_id = client.upsert("DefaultSpecification", "name", f"{transformation} yield factor for {for_type} {PLACEHOLDER_NOTE}", fields)
        print(f"  {for_type} via {transformation} = {factor}: {spec_id}")

    print("\nDone.")


if __name__ == "__main__":
    main()
