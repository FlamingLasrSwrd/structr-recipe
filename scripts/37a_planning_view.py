"""Give NutrientProfile the narrow view the planner reads its stored figures through
(mealplanner/planning_view_schema.py).

Schema only and idempotent, so like 30a to 36a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr before trusting a check made right after it (hard rule 8).

Run with: python3 scripts/37a_planning_view.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.planning_view_schema import OTHER_PROPERTIES, SCHEMA_PROPERTIES, TYPE, VIEW


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()
    (node,) = client.get("/structr/rest/SchemaNode", params={"name": TYPE})["result"]
    props = {}
    for name in SCHEMA_PROPERTIES:
        (prop,) = client.get("/structr/rest/SchemaProperty", params={"schemaNode": node["id"], "name": name})["result"]
        props[name] = prop["id"]
    others = ", ".join(OTHER_PROPERTIES)

    print(f"[1] View {TYPE}/{VIEW}...")
    existing = [v for v in client.get("/structr/rest/SchemaView", params={"name": VIEW})["result"]
                if (client.get_all("SchemaView", v["id"])["result"].get("schemaNode") or {}).get("id") == node["id"]]
    if len(existing) > 1:
        print(f"    [FAIL] {len(existing)} views named {VIEW!r} on {TYPE}; nothing changed")
        sys.exit(1)
    if not existing:
        client.post("/structr/rest/SchemaView", {"schemaNode": node["id"], "name": VIEW,
                                                 "schemaProperties": list(props.values()), "nonGraphProperties": others})
        print("    created")
    else:
        print("    exists")

    print("\n[2] Check...")
    (view,) = [v for v in client.get("/structr/rest/SchemaView", params={"name": VIEW})["result"]
               if (client.get_all("SchemaView", v["id"])["result"].get("schemaNode") or {}).get("id") == node["id"]]
    live = client.get_all("SchemaView", view["id"])["result"]
    have = {p["id"] for p in live.get("schemaProperties", [])}
    listed = {p.strip() for p in (live.get("nonGraphProperties") or "").split(",") if p.strip()}
    ok = have == set(props.values()) and listed == set(OTHER_PROPERTIES)
    print(f"    [{'OK' if ok else 'FAIL'}] {TYPE}/{VIEW}: {sorted(SCHEMA_PROPERTIES)} and {sorted(listed)}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
