"""Build order step 3, part A: metamodel node types (schema only).

Creates DomainType, TypeHierarchy, RelationKind as structural types
(they didn't exist after step 1 -- step 1 only covered the BFO tree
itself) plus their properties and relationships, and adds the scalar
properties QuantitySpecification needs to hold an actual value.

This is schema-building, safe to run before any metamodel DATA exists.
Run with: python3 scripts/03a_build_metamodel_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.metamodel_types import PROPERTIES, RELATIONSHIPS

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

NEW_TYPES = ["DomainType", "TypeHierarchy", "RelationKind"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Creating new metamodel SchemaNodes (DomainType, TypeHierarchy, "
          "RelationKind did not exist after step 1)...")
    name_to_id: dict[str, str] = {}
    for name in NEW_TYPES:
        node_id, created = client.ensure_type(name, is_abstract=False)
        name_to_id[name] = node_id
        print(f"    {name}: id={node_id}, created={created}")

    print("\n[2] Adding properties...")
    for type_name, props in PROPERTIES.items():
        existing = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"]
        if not existing:
            print(f"    SKIP {type_name} -- not found (should have been created in step 1 or above)")
            continue
        schema_node_id = existing[0]["id"]
        for prop in props:
            _, created = client.ensure_property(
                schema_node_id,
                prop["name"],
                prop["propertyType"],
                unique=prop.get("unique", False),
                indexed=prop.get("indexed", False),
                not_null=prop.get("notNull", False),
                format=prop.get("format"),
            )
            print(f"    {type_name}.{prop['name']}: created={created}")

    print("\n[3] Creating relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        source_lookup = name_to_id.get(source) or client.get(
            "/structr/rest/SchemaNode", params={"name": source}
        )["result"][0]["id"]
        target_lookup = name_to_id.get(target) or client.get(
            "/structr/rest/SchemaNode", params={"name": target}
        )["result"][0]["id"]
        rel_id, created = client.ensure_relationship(
            source_id=source_lookup,
            target_id=target_lookup,
            relationship_type=rel_type,
            source_multiplicity=src_mult,
            target_multiplicity=tgt_mult,
            source_json_name=src_json,
            target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  "
              f"(source.{tgt_json}, target.{src_json})  created={created}")

    print("\nMetamodel schema build complete.")


if __name__ == "__main__":
    main()
