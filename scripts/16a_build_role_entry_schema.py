"""Build the Role -> MealPlanEntry relation. See mealplanner/role_entry_schema.py.

Run with: python3 scripts/16a_build_role_entry_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.role_entry_schema import RELATIONSHIPS


def main():
    client = connect()
    client.wait_until_ready()

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
        print(f"{source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")


if __name__ == "__main__":
    main()
