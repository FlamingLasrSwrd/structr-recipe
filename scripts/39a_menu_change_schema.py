"""Let a skipped meal say what was eaten instead (data-model.md Sec 18 J34).

The owner asked (2026-10-24) for a way to change the menu as the week goes: a meal not made,
and what was eaten instead. A recipe from the book eaten instead is an entry of its own; anything
else is MealPlanEntry.eatenInstead on the skipped entry (mealplanner/menu_change_schema.py).

Schema only and idempotent, so like 30a to 38a it must also run against the owner's
instance (owner_data_ok=True). Restart Structr before trusting a check made right
after it (hard rule 8).

Run with: python3 scripts/39a_menu_change_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.menu_change_schema import PROPERTIES


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
