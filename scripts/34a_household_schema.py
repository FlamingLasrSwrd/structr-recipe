"""Build the schema for people, households and shared meals. See mealplanner/household_schema.py.

Schema only and idempotent, so like 30a to 33a it must also run against the owner's instance
(owner_data_ok=True). It creates the three new structural types there (a full build makes them
in script 01), then their relationships. The types are new and have no instances, so giving them
traits is the safe case (hard rule 2). Restart Structr before trusting a check made right after
it (hard rule 8).

Run with: python3 scripts/34a_household_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.household_schema import RELATIONSHIPS, TYPES
from mealplanner.structural_types import STRUCTURAL_TYPES, parents_of


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()
    print("[1] Types...")
    for name, is_abstract, parent in STRUCTURAL_TYPES:
        if name in TYPES:
            _, created = client.ensure_type(name, is_abstract=is_abstract, inherited_traits=parents_of(parent))
            print(f"    {name} inherits {parents_of(parent)}  created={created}")
    print("[2] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")
    print("[3] Read back...")
    ok = True
    for name, _, parent in STRUCTURAL_TYPES:
        if name in TYPES:
            live = client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0].get("inheritedTraits") or []
            good = sorted(live) == sorted(parents_of(parent))
            ok &= good
            print(f"    [{'OK' if good else 'FAIL'}] {name} inheritedTraits {sorted(live)}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
