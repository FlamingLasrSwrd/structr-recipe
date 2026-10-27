"""Six invariants checked on edits, on real Structr (docs/structr-features.md, batch 4; scripts/46a).

For each of QuantitySpecification, Measurement, Specification, Allocation, StockPolicy and
NutritionTarget (a PlanningConstraint) a valid TEST node is made, then edited so it breaks its
invariant (refused with the validator's token, and the stored value stays), and edited in a way
that keeps it (accepted). A related node is then deleted where a validator reads one (a StockPolicy's
threshold, a Specification's quantity): onSave runs then too, and must let it go. Everything is
TEST-named, swept before and deleted after.

Run with: python3 scripts/46b_onsave_validators_demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from structr_client import StructrError

P = "TEST -- Z46 "
WHEN = "2026-01-01T00:00:00+0000"
SWEEP_ORDER = ["StockPolicy", "NutritionTarget", "Allocation", "Specification", "Measurement", "QuantitySpecification"]


def sweep(client):
    for type_name in SWEEP_ORDER:
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

    def make(type_name, name, fields):
        return client.post(f"/structr/rest/{type_name}", {"name": P + name, "visibleToAuthenticatedUsers": True,
                                                         **fields})["result"][0]

    def refused(type_name, node_id, fields, token, kept):
        try:
            client.patch(f"/structr/rest/{type_name}/{node_id}", fields)
            ok = False
        except StructrError as e:
            ok = e.status == 422 and token in str(e.body)
        stored = client.get_all(type_name, node_id)["result"]
        same = all(stored.get(k) == v for k, v in kept.items())        # the stored values the edit would have changed
        check(ok and same, f"{type_name}: {', '.join(f'{k}={v}' for k, v in fields.items())} refused, {token}")

    def accepted(type_name, node_id, fields, label):
        try:
            client.patch(f"/structr/rest/{type_name}/{node_id}", fields)
            check(True, f"{type_name}: {label} accepted")
        except StructrError as e:
            check(False, f"{type_name}: {label} accepted (REFUSED: {str(e.body)[:120]})")

    sweep(client)
    try:
        print("[1] Edits that break an invariant, and edits that keep it...")
        grams = make("QuantitySpecification", "five grams", {"value": 5.0, "unit": "g", "status": "specified"})
        refused("QuantitySpecification", grams, {"minValue": 1.0}, "must_not_have_both_scalar_value_and_range", {"minValue": None})
        refused("QuantitySpecification", grams, {"unit": None}, "quantity_needs_a_unit", {"unit": "g"})
        accepted("QuantitySpecification", grams, {"value": 6.0}, "value 6")

        weighed = make("Measurement", "weighed", {"value": 5.0, "unit": "g", "status": "observed", "hasTime": WHEN})
        refused("Measurement", weighed, {"unit": None}, "quantity_needs_a_unit", {"unit": "g"})
        accepted("Measurement", weighed, {"value": 7.5}, "value 7.5")

        oven = make("Specification", "oven", {"hasParticipationRole": "instrument"})
        refused("Specification", oven, {"hasSpecifiedQuantity": grams}, "instrument_role_must_not_have_quantity", {})
        flour = make("Specification", "flour", {"hasParticipationRole": "input", "hasSpecifiedQuantity": grams})
        accepted("Specification", flour, {"isOptional": True}, "an input made optional")

        tool = make("Allocation", "a tool used", {"hasParticipationRole": "instrument"})
        refused("Allocation", tool, {"hasActualQuantity": weighed}, "instrument_role_must_not_have_quantity", {})

        target = make("QuantitySpecification", "target level", {"value": 500.0, "unit": "g", "status": "specified"})
        threshold = make("QuantitySpecification", "reorder threshold", {"value": 100.0, "unit": "g", "status": "specified"})
        pounds = make("QuantitySpecification", "threshold in pounds", {"value": 1.0, "unit": "lb", "status": "specified"})
        policy = make("StockPolicy", "policy", {"hasTargetLevel": target, "hasReorderThreshold": threshold, "strictness": "hard"})
        refused("StockPolicy", policy, {"hasReorderThreshold": pounds}, "target_and_reorder_threshold_must_share_a_unit", {})
        refused("StockPolicy", policy, {"strictness": "soft"}, "soft_constraint_requires_a_weight", {"strictness": "hard"})

        nutrition = make("NutritionTarget", "target", {"strictness": "hard"})
        refused("NutritionTarget", nutrition, {"strictness": "soft"}, "soft_constraint_requires_a_weight", {"strictness": "hard"})
        accepted("NutritionTarget", nutrition, {"strictness": "soft", "weight": 2.0}, "soft with a weight")

        print("\n[2] A related node deleted, where a validator reads one...")
        for label, type_name, node_id in (("the policy's reorder threshold", "QuantitySpecification", threshold),
                                          ("the flour's quantity", "QuantitySpecification", grams)):
            try:
                client.delete(f"/structr/rest/{type_name}/{node_id}")
                check(True, f"{label} deleted")
            except StructrError as e:
                check(False, f"{label} deleted (REFUSED: {str(e.body)[:120]})")
    finally:
        sweep(client)
    left = [n["name"] for t in SWEEP_ORDER for n in client.get_all(t)["result"] if (n.get("name") or "").startswith(P)]
    check(not left, "nothing TEST-named is left behind")
    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
