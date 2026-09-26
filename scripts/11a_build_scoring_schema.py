"""Build the simple-path scoring schema. See mealplanner/scoring_schema.py.

Run with: python3 scripts/11a_build_scoring_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.scoring_schema import PROPERTIES, RELATIONSHIPS


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] Properties...")
    for type_name, props in PROPERTIES.items():
        node = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"][0]
        for prop in props:
            _, created = client.ensure_property(
                node["id"], prop["name"], prop["propertyType"],
                unique=prop.get("unique", False), indexed=prop.get("indexed", False),
                not_null=prop.get("notNull", False), format=prop.get("format"),
            )
            print(f"    {type_name}.{prop['name']}: created={created}")

    print("\n[2] Relationships...")
    node_ids: dict[str, str] = {}
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        for name in (source, target):
            if name not in node_ids:
                node_ids[name] = client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]
        rel_id, created = client.ensure_relationship(
            source_id=node_ids[source], target_id=node_ids[target], relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")

    print("\nScoring schema build complete.")


if __name__ == "__main__":
    main()
