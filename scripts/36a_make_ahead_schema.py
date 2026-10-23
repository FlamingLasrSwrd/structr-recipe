"""Let a recipe say how long ahead it must be made (data-model.md Sec 18 J29).

The owner decided (2026-10-22) that a dish such as overnight oats, five minutes of
work and then eight hours of soaking, keeps its minutes for the work and states the
wait apart: Plan.makeAheadHours (mealplanner/make_ahead_schema.py).

Schema only and idempotent, so like 30a to 35a it must also run against the owner's
instance (owner_data_ok=True). Restart Structr before trusting a check made right
after it (hard rule 8).

Run with: python3 scripts/36a_make_ahead_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.make_ahead_schema import PROPERTIES


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


if __name__ == "__main__":
    main()
