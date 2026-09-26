"""Tests the write-time rules added after the second external review. Each
rejection is checked against its exact error token, and each has an accepted
control, so a rule that is too strict fails as visibly as one that is too lax.

  Measurement           a numeric value needs a unit (quantity_needs_a_unit)
  Measurement           hasTime is required (invariant 2)
  QuantitySpecification value, minValue and maxValue may not be negative
                        (invariant 12 was only checked on Measurement)
  QuantitySpecification a number needs a unit
  StockPolicy           target level and reorder threshold must share a unit,
                        because they are compared as bare numbers (500 g against
                        2 lb used to pass `500 >= 2`)

Everything accepted is deleted afterwards; a rejection creates nothing.

Run with: python3 scripts/24a_write_time_validator_checks.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient, StructrError

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- 24a "
WHEN = "2026-01-01T00:00:00+0000"


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    failures, made = [], []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def create(type_name, fields):
        """POST; returns (id, None) if accepted, (None, error text) if refused."""
        try:
            created = client.post(f"/structr/rest/{type_name}", {**fields, "visibleToAuthenticatedUsers": True})
        except StructrError as exc:
            return None, str(exc.body)
        node_id = created["result"][0]
        made.append((type_name, node_id))
        return node_id, None

    def refused(type_name, fields, token, label):
        node_id, error = create(type_name, fields)
        check(node_id is None and error is not None and token in error,
              f"{label} -> refused with {token!r}" + ("" if node_id is None else " (ACCEPTED!)"))

    def accepted(type_name, fields, label):
        node_id, error = create(type_name, fields)
        check(node_id is not None, f"{label} -> accepted" + ("" if node_id else f" (REFUSED: {error[:90]})"))
        return node_id

    try:
        print("[1] Measurement: a value needs a unit, and a time is required...")
        good = {"value": 5.0, "unit": "g", "status": "observed", "hasTime": WHEN}
        accepted("Measurement", {**good, "name": P + "measurement control"}, "value + unit + time")
        refused("Measurement", {"name": P + "no unit", "value": 5.0, "status": "observed", "hasTime": WHEN},
                "quantity_needs_a_unit", "value without a unit")
        node_id, error = create("Measurement", {"name": P + "no time", "value": 5.0, "unit": "g", "status": "observed"})
        check(node_id is None and error and "hasTime" in error, f"no hasTime -> refused, naming hasTime ({(error or 'ACCEPTED!')[:90]})")

        print("\n[2] QuantitySpecification: no negatives, and a number needs a unit...")
        accepted("QuantitySpecification", {"name": P + "qty control", "value": 5.0, "unit": "g", "status": "specified"}, "scalar 5 g")
        accepted("QuantitySpecification", {"name": P + "range control", "minValue": 0.0, "maxValue": 5.0, "unit": "g", "status": "specified"},
                 "range 0-5 g (a zero bound is fine)")
        refused("QuantitySpecification", {"name": P + "negative value", "value": -1.0, "unit": "g", "status": "specified"},
                "must_not_be_negative", "negative scalar")
        refused("QuantitySpecification", {"name": P + "negative min", "minValue": -10.0, "maxValue": 50.0, "unit": "g", "status": "specified"},
                "must_not_be_negative", "negative minValue with a valid maxValue")
        refused("QuantitySpecification", {"name": P + "negative max", "maxValue": -5.0, "unit": "g", "status": "specified"},
                "must_not_be_negative", "negative maxValue alone")
        refused("QuantitySpecification", {"name": P + "no unit", "value": 5.0, "status": "specified"},
                "quantity_needs_a_unit", "a number without a unit")

        print("\n[3] StockPolicy: target and threshold must share a unit...")
        g_500 = accepted("QuantitySpecification", {"name": P + "500 g", "value": 500.0, "unit": "g", "status": "specified"}, "500 g")
        g_100 = accepted("QuantitySpecification", {"name": P + "100 g", "value": 100.0, "unit": "g", "status": "specified"}, "100 g")
        lb_2 = accepted("QuantitySpecification", {"name": P + "2 lb", "value": 2.0, "unit": "lb", "status": "specified"}, "2 lb")
        chicken = client.get("/structr/rest/DomainType", params={"name": "Chicken Breast (raw)"})["result"][0]["id"]
        base = {"appliesTo": chicken, "strictness": "hard", "includesSubtypes": True}
        accepted("StockPolicy", {**base, "name": P + "policy control", "hasTargetLevel": g_500, "hasReorderThreshold": g_100},
                 "target 500 g >= threshold 100 g")
        refused("StockPolicy", {**base, "name": P + "policy mixed units", "hasTargetLevel": g_500, "hasReorderThreshold": lb_2},
                "target_and_reorder_threshold_must_share_a_unit", "500 g against 2 lb (would have passed 500 >= 2)")
        refused("StockPolicy", {**base, "name": P + "policy target below", "hasTargetLevel": g_100, "hasReorderThreshold": g_500},
                "target_level_must_be_at_least_reorder_threshold", "same unit but target below threshold (the original rule still holds)")
    finally:
        for type_name, node_id in reversed(made):
            client.delete(f"/structr/rest/{type_name}/{node_id}")
        print(f"\n[cleanup] removed {len(made)} accepted control node(s)")

    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
