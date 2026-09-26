"""Build ContainerObject.hasOpenedStatus and seed the Opened Status
vocabulary. See mealplanner/opened_status_schema.py.

Run with: python3 scripts/17a_build_opened_status.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.opened_status_schema import RELATIONSHIPS, OPENED_STATUS_HIERARCHY, OPENED_STATUS_VALUES


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] Relationship...")
    node_ids = {}
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        for name in (source, target):
            if name not in node_ids:
                node_ids[name] = client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]
        rel_id, created = client.ensure_relationship(
            source_id=node_ids[source], target_id=node_ids[target], relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  created={created}")

    print("\n[2] Opened Status vocabulary...")
    hier_id = client.upsert("TypeHierarchy", "name", OPENED_STATUS_HIERARCHY, {"singleParent": True})
    value_ids = {}
    for name in OPENED_STATUS_VALUES:
        value_ids[name] = client.upsert("DomainType", "name", name, {"isLookupBearing": True, "hierarchy": hier_id})
        print(f"    {name}: {value_ids[name]}")


if __name__ == "__main__":
    main()
