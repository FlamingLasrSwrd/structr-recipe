"""Build order step 4: one lifecycle-method invariant end to end.

Confirms the SHACL-substitute pattern (structr-build-sketch.md Sec 5:
"onCreate / onSave validators on various traits -- the 30 domain
invariants") is real, using data-model.md Sec 11 invariant 12:
"No quantity-bearing value may be negative."

Implemented as an onCreate SchemaMethod on Measurement. Mechanism
(see structr-cheatsheet.md Sec 3a addendum): StructrScript's error(
property, token) function aborts the transaction with a 422 carrying
that property/token -- confirmed empirically, not documented anywhere
before this project.

Run with: python3 scripts/04_lifecycle_invariant.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient, StructrError

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

# and(not(empty(this.value)), ...) guards against categorical
# Measurements that carry only `literalValue` and no numeric `value` --
# found the hard way in step 6 when lt(null, 0) evaluated true,
# rejecting every categorical Measurement (opened_status, cleanliness)
# outright.
INVARIANT_12_SOURCE = (
    'if(and(not(empty(this.value)), lt(this.value, 0)), '
    'error("value", "must_not_be_negative"), null)'
)


# A fixed instant, not "now": these fixtures only prove the value check, and
# Measurement.hasTime is required (invariant 2).
OBSERVED_AT = "2026-01-01T00:00:00+0000"


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    measurement = client.get("/structr/rest/SchemaNode", params={"name": "Measurement"})["result"][0]
    mid = measurement["id"]

    print("[1] Ensuring Measurement.value/unit/status properties...")
    client.ensure_property(mid, "value", "Double")
    client.ensure_property(mid, "unit", "String")
    client.ensure_property(mid, "status", "Enum", format="observed,imputed,derived,estimated")

    print("\n[2] Ensuring onCreate validator (invariant 12: no negative quantity-bearing value)...")
    # Install this spike's simple validator ONLY if none exists. scripts/07
    # later installs the full Measurement.onCreate (units, nutrient rules,
    # duplicate-observation rule) as the same SchemaMethod, and ensure_method
    # overwrites. Re-running this script after 07 used to silently replace the
    # full validator with this negative-only one, downgrading the schema
    # (found while deploying new validators: 24a caught a unit-less
    # Measurement being accepted).
    existing = client.get("/structr/rest/SchemaMethod", params={"schemaNode": mid, "name": "onCreate"})["result"]
    if existing:
        print(f"    a Measurement.onCreate already exists (id={existing[0]['id']}); leaving it alone -- "
              f"scripts/07 owns the full version")
    else:
        method_id, created = client.ensure_method(
            mid, "onCreate", INVARIANT_12_SOURCE, return_raw_result=False
        )
        print(f"    method id={method_id}, created={created}")

    print("\n[3] Verifying: negative rejected, zero and positive accepted...")
    all_ok = True

    try:
        client.post(
            "/structr/rest/Measurement",
            {
                "name": "TEST -- invariant 12 negative value (should be rejected)",
                "value": -3.0, "unit": "g", "status": "observed", "hasTime": OBSERVED_AT,
                "visibleToAuthenticatedUsers": True,
            },
        )
        print("    [FAIL] negative value was accepted (should have been rejected)")
        all_ok = False
    except StructrError as e:
        ok = e.status == 422 and e.body.get("errors", [{}])[0].get("token") == "must_not_be_negative"
        print(f"    [{'OK' if ok else 'FAIL'}] negative value rejected: {e.status} {e.body}")
        all_ok &= ok

    # upsert, not post: a re-run should find these rather than duplicate them.
    # (The negative case above stays a POST -- a rejected create is the test.)
    zero_id = client.upsert(
        "Measurement", "name", "TEST -- invariant 12 zero value (boundary - should be accepted)",
        {"value": 0.0, "unit": "g", "status": "observed", "hasTime": OBSERVED_AT},
    )
    print(f"    [OK] zero value accepted: {zero_id}")

    positive_id = client.upsert(
        "Measurement", "name", "TEST -- invariant 12 positive value (should be accepted)",
        {"value": 12.5, "unit": "g", "status": "observed", "hasTime": OBSERVED_AT},
    )
    print(f"    [OK] positive value accepted: {positive_id}")

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. The SHACL-substitute pattern (onCreate validators "
          "enforcing the model's domain invariants) is confirmed real end to end.")


if __name__ == "__main__":
    main()
