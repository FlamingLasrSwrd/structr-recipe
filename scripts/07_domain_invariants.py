"""Build the domain-invariant validators from mealplanner/domain_invariants.py.

Supersedes script 04's narrower single-invariant version (kept for
history; this is the authoritative, idempotent build going forward).

Run with: python3 scripts/07_domain_invariants.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.domain_invariants import (
    MEASUREMENT_ONCREATE,
    SPECIFICATION_ONCREATE,
    ALLOCATION_ONCREATE,
    DEFAULT_SPECIFICATION_ONCREATE,
    NOT_NULL_PROPERTIES,
)


def node_id(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] onCreate validators...")
    for type_name, source in [
        ("Measurement", MEASUREMENT_ONCREATE),
        ("Specification", SPECIFICATION_ONCREATE),
        ("Allocation", ALLOCATION_ONCREATE),
        ("DefaultSpecification", DEFAULT_SPECIFICATION_ONCREATE),
    ]:
        method_id, created = client.ensure_method(node_id(client, type_name), "onCreate", source, return_raw_result=False)
        print(f"    {type_name}.onCreate: id={method_id}, created={created}")

    print("\n[2] notNull constraints...")
    for type_name, prop_name in NOT_NULL_PROPERTIES:
        nid = node_id(client, type_name)
        prop = client.get("/structr/rest/SchemaProperty", params={"schemaNode": nid, "name": prop_name})["result"][0]
        client.patch(f"/structr/rest/SchemaProperty/{prop['id']}", {"notNull": True})
        print(f"    {type_name}.{prop_name}: notNull=True")

    print("\nDomain invariant validators built. See mealplanner/domain_invariants.py "
          "for what's covered, what's structurally free, and what's deferred pending "
          "unbuilt structural pieces.")


if __name__ == "__main__":
    main()
