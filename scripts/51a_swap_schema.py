"""Let a week's meals use a food bought in place of what the shopping list says, and a cook record the
rule it followed (mealplanner/swap_schema.py, mealplanner/substitutes.py; data-model.md J42).

Schema only and idempotent, so like 30a to 49a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr before trusting a check made right after it (hard rule 8).
Until it has run, the shopping page's "Bought instead" refuses, and everything reads a week as before.

Run with: python3 scripts/51a_swap_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.swap_schema import PROPERTIES, RELATIONSHIPS


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    print("[1] Properties...")
    for type_name, props in PROPERTIES.items():
        node = schema_node(client, type_name)
        for prop in props:
            _, created = client.ensure_property(node, prop["name"], prop["propertyType"], format=prop.get("format"))
            print(f"    {type_name}.{prop['name']} ({prop['propertyType']})  created={created}")

    print("[2] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")


if __name__ == "__main__":
    main()
