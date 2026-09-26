"""Build order step 3, part C: the resolveDefault SchemaMethod.

Per structr-build-sketch.md Sec 5: `resolveDefault(kind)` on DomainType,
"walk SUBCLASS_OF* upward, nearest wins, return the QuantitySpecification
or nothing."

IMPLEMENTATION NOTE -- this does NOT use recursion. Extensive empirical
probing (recorded in structr-cheatsheet.md Sec 3a) found no working
mechanism for passing a value into a nested internal SchemaMethod call
(this.parent.resolveDefault(x)) in this Structr 6.0.0 Community setup --
neither retrieve()/store(), nor a declared SchemaMethodParameter, carry
a value across the call boundary. What DOES work is chained property
access (this.parent.parent...) within a SINGLE script execution, where
retrieve() stays valid throughout. So this method unrolls the upward
walk as nested if() expressions over a fixed maximum depth instead of
true recursion.

MAX_DEPTH below bounds how many hierarchy levels can be walked. This is
a real, documented limitation -- not a full implementation of an
unbounded-depth subsumption walk. A hierarchy deeper than MAX_DEPTH
would silently stop resolving past that point. Flagged here rather than
worked around silently, per CLAUDE.md's guidance on genuine findings.

Run with: python3 scripts/03c_build_resolve_default.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

MAX_DEPTH = 6  # see docstring -- a real, documented bound, not unbounded recursion


def _has_match(path: str) -> str:
    return f'gt(size(filter({path}.defaultSpecifications, equal(data.hasKind.id, retrieve("kindId")))), 0)'


def _match(path: str) -> str:
    return f'first(filter({path}.defaultSpecifications, equal(data.hasKind.id, retrieve("kindId")))).hasValue'


def _build(level: int) -> str:
    path = "this" + ".parent" * level
    parent_path = path + ".parent"
    inner = "null" if level == MAX_DEPTH - 1 else _build(level + 1)
    return f"if({_has_match(path)}, {_match(path)}, if(empty({parent_path}), null, {inner}))"


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    domain_type = client.get("/structr/rest/SchemaNode", params={"name": "DomainType"})["result"][0]
    source = _build(0)

    print(f"[1] ensure_method resolveDefault on DomainType (max depth {MAX_DEPTH})...")
    method_id, created = client.ensure_method(domain_type["id"], "resolveDefault", source)
    print(f"    method id={method_id}, created={created}, source length={len(source)}")

    print("\n[2] Verifying against the test chain built in 03b "
          "(re-looking-up IDs by name, not hardcoded, since this script "
          "should be independently re-runnable)...")

    def domain_type_id(name: str) -> str:
        return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]

    poultry = domain_type_id("TEST -- Poultry")
    chicken = domain_type_id("TEST -- Chicken Breast (raw)")
    fresh_meat = domain_type_id("TEST -- Fresh Meat")
    density = domain_type_id("TEST -- Density")

    cases = [
        ("Poultry, own default (depth 0)", poultry, density, "TEST -- density value for Poultry default"),
        ("Chicken Breast (raw), walk up 1 level", chicken, density, "TEST -- density value for Poultry default"),
        ("Fresh Meat, root, no default above -> null", fresh_meat, density, None),
        ("Chicken Breast (raw), non-matching kind -> null", chicken, "nonexistent-id", None),
    ]

    all_ok = True
    for label, node_id, kind_id, expected_name in cases:
        result = client.call_method("DomainType", node_id, "resolveDefault", {"kindId": kind_id})
        if expected_name is None:
            ok = result in (None, [], {})
        else:
            ok = isinstance(result, dict) and result.get("name") == expected_name
        all_ok &= ok
        print(f"    [{'OK' if ok else 'FAIL'}] {label} -> {result}")

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. resolveDefault built idempotently and verified.")
    print("\nReminder: this was verified once already directly via curl, then "
          "AGAIN after a full container restart (per the cheatsheet's warning "
          "against trusting a spike run right after a schema change) -- both "
          "passed identically.")


if __name__ == "__main__":
    main()
