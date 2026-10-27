"""Invariant 12 on edits, on real Structr (docs/structr-features.md, batch 3; scripts/45a).

A TEST QuantitySpecification and a TEST Measurement, each made with a valid value, are edited:
to a negative value (refused, and the stored value stays), past the interval's upper bound
(refused), and to another valid value (accepted). A create is refused below zero by the onCreate
validator, whose error ends the request before the format is checked, and past the bound by the
format. Everything is TEST-named, swept before and deleted after.

Run with: python3 scripts/45b_non_negative_format_demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.domain_invariants import NON_NEGATIVE_FORMAT, NON_NEGATIVE_PROPERTIES
from structr_client import StructrError

P = "TEST -- Z45 "
WHEN = "2026-01-01T00:00:00+0000"


def sweep(client):
    for type_name in ("Measurement", "QuantitySpecification"):
        for node in client.get_all(type_name)["result"]:
            if (node.get("name") or "").startswith(P):
                client.delete(f"/structr/rest/{type_name}/{node['id']}")


def main():
    client = connect()
    client.wait_until_ready()
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def refused(call, token="must_be_in_range"):
        try:
            call()
        except StructrError as e:
            return e.status == 422 and token in str(e.body)
        return False

    sweep(client)
    try:
        print("[1] The format on each property (45a)...")
        for type_name, key in NON_NEGATIVE_PROPERTIES:
            node = client.get("/structr/rest/SchemaNode", params={"name": type_name})["result"][0]["id"]
            prop = client.get("/structr/rest/SchemaProperty", params={"schemaNode": node, "name": key})["result"][0]
            check(prop.get("format") == NON_NEGATIVE_FORMAT, f"{type_name}.{key} has {NON_NEGATIVE_FORMAT}")

        print("\n[2] Edits...")
        qty = client.upsert("QuantitySpecification", "name", P + "five grams", {"value": 5.0, "unit": "g", "status": "specified"})
        rng = client.upsert("QuantitySpecification", "name", P + "a range", {"minValue": 1.0, "maxValue": 9.0, "unit": "g",
                                                                            "status": "specified"})
        meas = client.upsert("Measurement", "name", P + "a measurement", {"value": 12.5, "unit": "g", "status": "observed",
                                                                          "hasTime": WHEN})
        for type_name, node_id, key, start in (("QuantitySpecification", qty, "value", 5.0),
                                               ("QuantitySpecification", rng, "minValue", 1.0),
                                               ("QuantitySpecification", rng, "maxValue", 9.0),
                                               ("Measurement", meas, "value", 12.5)):
            path = f"/structr/rest/{type_name}/{node_id}"
            check(refused(lambda: client.patch(path, {key: -1.0})), f"{type_name}.{key} edited to -1: refused")
            check(client.get_all(type_name, node_id)["result"].get(key) == start, f"  and still {start}")
            check(refused(lambda: client.patch(path, {key: 2e9})), f"{type_name}.{key} edited to 2e9: refused")
        client.patch(f"/structr/rest/QuantitySpecification/{qty}", {"value": 0.0})
        check(client.get_all("QuantitySpecification", qty)["result"].get("value") == 0.0, "a value edited to 0: accepted")

        print("\n[3] Creates...")
        made = lambda value: lambda: client.post("/structr/rest/QuantitySpecification", {
            "name": P + "made", "value": value, "unit": "g", "status": "specified", "visibleToAuthenticatedUsers": True})
        # The onCreate validator's error ends the request before Structr checks the format, so a negative
        # create is refused with the validator's token alone; past the bound, only the format refuses
        check(refused(made(-2.0), "must_not_be_negative"), "made at -2: refused by the validator (invariant 12)")
        check(refused(made(2e9)), "made at 2e9: refused by the format")
    finally:
        sweep(client)
    left = [n["name"] for t in ("Measurement", "QuantitySpecification") for n in client.get_all(t)["result"]
            if (n.get("name") or "").startswith(P)]
    check(not left, "nothing TEST-named is left behind")
    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
