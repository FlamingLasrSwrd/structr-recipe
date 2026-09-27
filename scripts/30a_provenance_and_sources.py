"""Let every figure say how sure it is and where it came from (data-model.md Sec 18 J21).

The owner decided (2026-09-27) that an estimate is good enough to plan with,
provided it says it is one and names its source, so it can be checked and
replaced later. This migrates an instance built before that decision:

  - NutrientProfile.provenance gains "estimated" and "calculated" (it was
    "placeholder,sourced"). The drift-refusing schema helper will not widen an
    enum, so the SchemaProperty's format is changed here, once.
  - NutrientProfile.source, DefaultSpecification.provenance and
    DefaultSpecification.source are added.

Schema only: no node's data is touched, and it is idempotent. That makes it one
of the few numbered scripts that must also run against the owner's instance, so
it connects with owner_data_ok=True. Restart Structr before trusting a check
made right after it (hard rule 8).

Run with: python3 scripts/30a_provenance_and_sources.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.nutrition_schema import OLD_PROVENANCE_FORMAT, PROVENANCE_FORMAT
from mealplanner.nutrition_schema import PROPERTIES as NUTRITION_PROPERTIES
from mealplanner.provenance_schema import PROPERTIES


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    print("[1] NutrientProfile.provenance values...")
    node = schema_node(client, "NutrientProfile")
    (prop,) = client.get("/structr/rest/SchemaProperty", params={"schemaNode": node, "name": "provenance"})["result"]
    live = client.get_all("SchemaProperty", prop["id"])["result"].get("format")
    if live == OLD_PROVENANCE_FORMAT:
        client.patch(f"/structr/rest/SchemaProperty/{prop['id']}", {"format": PROVENANCE_FORMAT})
        print(f"    widened: {OLD_PROVENANCE_FORMAT!r} -> {PROVENANCE_FORMAT!r}")
    elif live == PROVENANCE_FORMAT:
        print("    already widened")
    else:
        print(f"    [FAIL] unexpected format {live!r}; nothing changed")
        sys.exit(1)

    print("\n[2] source, and DefaultSpecification.provenance...")
    wanted = [("NutrientProfile", p) for p in NUTRITION_PROPERTIES["NutrientProfile"] if p["name"] in ("provenance", "source")]
    wanted += [(t, p) for t, props in PROPERTIES.items() for p in props]
    for type_name, p in wanted:
        _, created = client.ensure_property(schema_node(client, type_name), p["name"], p["propertyType"],
                                            format=p.get("format"))
        print(f"    {type_name}.{p['name']}: created={created}")

    print("\n[3] Check...")
    live = client.get_all("SchemaProperty", prop["id"])["result"].get("format")
    ok = live == PROVENANCE_FORMAT
    print(f"    [{'OK' if ok else 'FAIL'}] NutrientProfile.provenance is {live!r}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
