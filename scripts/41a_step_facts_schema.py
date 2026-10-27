"""Let a recipe's steps say how long they take, at what heat, until what, and in what order
(data-model.md Sec 18 J35; mealplanner/step_facts_schema.py).

The relationships a Step needs for its working and waiting time and for the steps before it, and the
three Quality Kinds heat and doneness name (Temperature, Heat Level, Doneness), which a Specification's
StateRequirements target. The kinds are vocabulary the model needs, as script 05's Mass is, not owner
data: shared, visible to every signed-in user.

Schema and shared vocabulary only, and idempotent, so like 30a to 40a it must also run against the
owner's instance (owner_data_ok=True). Restart Structr before trusting a check made right after it
(hard rule 8).

Run with: python3 scripts/41a_step_facts_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.step_facts_schema import QUALITY_KIND_HIERARCHY, QUALITY_KINDS, RELATIONSHIPS


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema and shared vocabulary; the owner's instance needs them too
    client.wait_until_ready()

    print("[1] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")

    print("[2] Quality Kinds...")
    found = [h for h in client.get("/structr/rest/TypeHierarchy", params={"name": QUALITY_KIND_HIERARCHY})["result"]
             if h.get("type") == "TypeHierarchy"]
    if len(found) != 1:
        raise SystemExit(f"expected one TypeHierarchy named {QUALITY_KIND_HIERARCHY!r} (script 05 makes it), found {len(found)}")
    for name in QUALITY_KINDS:
        before = [d for d in client.get("/structr/rest/DomainType", params={"name": name})["result"] if d.get("type") == "DomainType"]
        for d in before:                      # never move a type of this name out of another hierarchy
            if (client.get_all("DomainType", d["id"])["result"].get("hierarchy") or {}).get("id") != found[0]["id"]:
                raise SystemExit(f"a DomainType named {name!r} exists outside {QUALITY_KIND_HIERARCHY!r}: rename one first")
        client.upsert("DomainType", "name", name, {"hierarchy": found[0]["id"], "isLookupBearing": False})
        print(f"    {name}  created={not before}")


if __name__ == "__main__":
    main()
