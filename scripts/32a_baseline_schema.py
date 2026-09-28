"""Build the schema a daily baseline needs. See mealplanner/baseline_schema.py.

Schema only and idempotent, so like 30a and 31a it must also run against the
owner's instance (owner_data_ok=True). Restart Structr before trusting a check
made right after it (hard rule 8).

Run with: python3 scripts/32a_baseline_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.baseline_schema import RELATIONSHIPS
from mealplanner.connection import connect


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()
    print("[1] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")


if __name__ == "__main__":
    main()
