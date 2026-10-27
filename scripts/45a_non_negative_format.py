"""Invariant 12, "no quantity-bearing value may be negative", checked by Structr on edits as well as
creates (docs/structr-features.md, batch 3; mealplanner/domain_invariants.py NON_NEGATIVE_FORMAT).

The onCreate validators (scripts/04, 07, 10b) refuse a negative value when a node is created, but
not when one is changed later, through REST or a page. A numeric `format` interval on the property
is checked on every write (the format spike): this sets it on QuantitySpecification value, minValue
and maxValue and on Measurement value, where a build made before declared them without it. A
fresh build declares it from the start (03a, 04, 10a), so there this changes nothing.

It first reads every stored value and stops, changing nothing, if one is outside the interval:
such a value needs looking at before the rule is declared.

Schema only and idempotent, so like 30a to 44a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr after it before trusting a check (hard rule 8).

Run with: python3 scripts/45a_non_negative_format.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.domain_invariants import NON_NEGATIVE_FORMAT, NON_NEGATIVE_PROPERTIES

LOW, HIGH = (float(x) for x in NON_NEGATIVE_FORMAT.strip("[]").split(","))


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    print("[1] Stored values outside", NON_NEGATIVE_FORMAT, "...")
    outside = []
    for type_name in sorted({t for t, _ in NON_NEGATIVE_PROPERTIES}):
        keys = [k for t, k in NON_NEGATIVE_PROPERTIES if t == type_name]
        for row in client.get_all(type_name)["result"]:
            for key in keys:
                value = row.get(key)
                if value is not None and not LOW <= value <= HIGH:
                    outside.append(f"{type_name} {row.get('name') or row['id']}: {key} = {value}")
    for line in outside:
        print(f"    {line}")
    if outside:
        print(f"FAILED: {len(outside)} stored value(s) outside {NON_NEGATIVE_FORMAT}; nothing was changed")
        sys.exit(1)
    print("    none")

    print("[2] The format on each property...")
    for type_name, key in NON_NEGATIVE_PROPERTIES:
        node = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"][0]["id"]
        prop = client.get("/structr/rest/SchemaProperty", params={"schemaNode": node, "name": key})["result"][0]
        changed = prop.get("format") != NON_NEGATIVE_FORMAT
        if changed:
            client.patch(f"/structr/rest/SchemaProperty/{prop['id']}", {"format": NON_NEGATIVE_FORMAT})
        print(f"    {type_name}.{key}  set={changed}")


if __name__ == "__main__":
    main()
