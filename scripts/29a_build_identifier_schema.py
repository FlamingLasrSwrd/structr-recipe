"""Build the Identifier schema and its scheme Concepts. See mealplanner/identifier_schema.py.

Then check the load-bearing part on this instance: an Identifier created now
denotes nodes created long before DENOTES was declared, an instance through
`denotes` and a Type through `denotesType`, and both directions read back. The
throwaway Identifier is TEST-named and deleted again.

Run with: python3 scripts/29a_build_identifier_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.identifier_schema import PROPERTIES, RELATIONSHIPS, SCHEME, SCHEME_CONCEPTS, WEB_PAGE
from mealplanner.typetree import dt

PROBE = "TEST -- Z29 identifier probe"


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] Properties...")
    for type_name, props in PROPERTIES.items():
        node = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"][0]
        for prop in props:
            _, created = client.ensure_property(
                node["id"], prop["name"], prop["propertyType"], unique=prop.get("unique", False),
                indexed=prop.get("indexed", False), not_null=prop.get("notNull", False), format=prop.get("format"),
            )
            print(f"    {type_name}.{prop['name']}: created={created}")

    print("\n[2] Relationships...")
    node_ids: dict[str, str] = {}
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        for name in (source, target):
            if name not in node_ids:
                node_ids[name] = client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]
        _, created = client.ensure_relationship(
            source_id=node_ids[source], target_id=node_ids[target], relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")

    print("\n[3] The Identifier Scheme and its Concepts...")
    scheme_id = client.upsert("ConceptScheme", "name", SCHEME, {})
    for name in SCHEME_CONCEPTS:
        client.upsert("Concept", "name", name, {"inScheme": scheme_id})
        print(f"    {name}")

    print("\n[4] Probes: Identifiers denoting nodes older than DENOTES...")
    for stale in client.get("/structr/rest/Identifier", params={"name": PROBE})["result"]:
        client.delete(f"/structr/rest/Identifier/{stale['id']}")
    web_page = client.get("/structr/rest/Concept", params={"name": WEB_PAGE})["result"][0]["id"]
    all_ok = True
    # An Entity (the Dinner Concept, seeded in 13b) through `denotes`, and a Type
    # (Braising, seeded in 05) through `denotesType`.
    for label, type_name, target, forward_name in (
        ("an instance", "Concept", client.get("/structr/rest/Concept", params={"name": "Dinner"})["result"][0]["id"], "denotes"),
        ("a Type", "DomainType", dt(client, "Braising"), "denotesType"),
    ):
        probe = client.upsert("Identifier", "name", PROBE, {
            "identifierValue": "https://example.org/probe", "identifierScheme": web_page, forward_name: target})
        try:
            forward = client.get_all("Identifier", probe)["result"]
            back = client.get_all(type_name, target)["result"].get("identifiers", [])
            ok = ((forward.get(forward_name) or {}).get("id") == target
                  and (forward.get("identifierScheme") or {}).get("name") == WEB_PAGE
                  and forward.get("identifierValue") == "https://example.org/probe"
                  and [r["id"] for r in back] == [probe])
        finally:
            client.delete(f"/structr/rest/Identifier/{probe}")
        print(f"    [{'OK' if ok else 'FAIL'}] {label} through {forward_name}: value, scheme and both directions read back")
        all_ok &= ok
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
