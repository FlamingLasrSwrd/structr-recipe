"""Retire the StructrScript `resolveDefault` method on DomainType (REVIEW.md round 3, #6).

scripts/03c built it in build-order step 3, the spike that showed a Type's defaults could be
found by walking its parents. It filters only by kind, never by `keyedBy`, so a Type with two
defaults of one kind keyed differently got whichever came first (round 2, #5), and it walks at
most six levels. Since then mealplanner/defaults.py resolves by kind and keys, with no depth
limit, and every caller uses it; the pages repeat that in JavaScript (pages/lib/10_units.js).
Nothing calls the method, and it disagrees with the resolver that is used.

A fresh build no longer makes it (03c now checks the walk through mealplanner/defaults.py, and
05, 08 and 14a check their defaults the same way), so there this changes nothing. On an instance
built before, it deletes the method. Only that one: a method of that name on another type, or any
other method on DomainType, is left alone.

Schema only and idempotent, so like 30a to 46a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr after it before trusting a check (hard rule 8).

Run with: python3 scripts/47a_retire_resolve_default.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

TYPE, METHOD = "DomainType", "resolveDefault"


def retired_methods(client) -> list[str]:
    """The ids of the resolveDefault methods on DomainType, which this removes."""
    nodes = client.get("/structr/rest/SchemaNode", params={"name": TYPE})["result"]
    if not nodes:
        return []
    owner = nodes[0]["id"]
    return [m["id"] for m in client.get("/structr/rest/SchemaMethod", params={"name": METHOD})["result"]
            if (m.get("schemaNode") or {}).get("id") == owner]


def retire(client) -> int:
    """Delete them; returns how many there were."""
    found = retired_methods(client)
    for method_id in found:
        client.delete(f"/structr/rest/SchemaMethod/{method_id}")
    return len(found)


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()
    print(f"[1] {TYPE}.{METHOD}...")
    removed = retire(client)
    print(f"    removed {removed}" if removed else "    not there; nothing to do")
    left = retired_methods(client)
    if left:
        print(f"FAILED: {len(left)} still there after the delete")
        sys.exit(1)
    print("\nAll checks passed. Restart Structr before trusting a check (hard rule 8).")


if __name__ == "__main__":
    main()
