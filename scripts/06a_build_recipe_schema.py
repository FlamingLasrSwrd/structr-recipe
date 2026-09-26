"""Build order step 6, part A: schema additions for the plan side,
inventory, and execution. See mealplanner/recipe_schema.py for design
notes -- all additive, no renames, new relationships declared on
abstract traits where that avoids per-concrete-type duplication
(confirmed safe by an isolated probe before this was written).

Run with: python3 scripts/06a_build_recipe_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.recipe_schema import PROPERTIES, RELATIONSHIPS

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Adding properties...")
    for type_name, props in PROPERTIES.items():
        node = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"][0]
        for prop in props:
            _, created = client.ensure_property(
                node["id"], prop["name"], prop["propertyType"],
                unique=prop.get("unique", False),
                indexed=prop.get("indexed", False),
                not_null=prop.get("notNull", False),
                format=prop.get("format"),
            )
            print(f"    {type_name}.{prop['name']}: created={created}")

    print("\n[2] Creating relationships...")
    node_ids: dict[str, str] = {}
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        for name in (source, target):
            if name not in node_ids:
                node_ids[name] = client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]
        rel_id, created = client.ensure_relationship(
            source_id=node_ids[source], target_id=node_ids[target],
            relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  "
              f"(source.{tgt_json}, target.{src_json})  created={created}")

    print("\nRecipe schema build complete.")


if __name__ == "__main__":
    main()
