"""Check six of the domain invariants on edits too, not only as a node is made (docs/structr-features.md,
batch 4; mealplanner/domain_invariants.py ONSAVE_TWINS).

For QuantitySpecification, Measurement, Specification, Allocation, StockPolicy and PlanningConstraint
this installs an onSave method with the onCreate validator's own source. Structr runs it on every
PUT or PATCH of the node, and whenever its relationships change; these six read only the node's own
properties, or a related node behind an empty() guard, so it refuses an edit only when the edit
breaks the invariant. The other four validators stay onCreate only (domain_invariants.py says why).

An onSave refuses any edit of a node that already breaks its invariant, so first every stored node
of the six types is checked against its validator, and nothing is installed if one fails: a
throwaway function evaluates each validator, its errors turned into plain strings
(domain_invariants.as_check), against every node of the type, and is removed again.

Schema only and idempotent, so like 30a to 45a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr after it before trusting a check (hard rule 8).

Run with: python3 scripts/46a_onsave_validators.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.domain_invariants import ONSAVE_TWINS, as_check

CHECK = "invariantCheck46a"            # the throwaway function: made, called, and removed by this script
CHECK_SOURCE = """{
  const out = {count: 0, broken: []};
  for (const n of $.find($.args.type)) {
    out.count++;
    const said = $.evaluateScript(n, $.args.check);
    if (said !== null && said !== undefined && String(said) !== '') {
      out.broken.push((n.name || n.id) + ': ' + String(said));
    }
  }
  return out;
}"""


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def stored_breaches(client) -> list[str]:
    """Every stored node of the six types its validator would refuse, one line each."""
    for old in client.get("/structr/rest/SchemaMethod", params={"name": CHECK})["result"]:
        client.delete(f"/structr/rest/SchemaMethod/{old['id']}")          # left by an interrupted run
    method = client.post("/structr/rest/SchemaMethod", {"name": CHECK, "source": CHECK_SOURCE,
                                                       "returnRawResult": True})["result"][0]
    try:
        found = []
        for type_name, source in ONSAVE_TWINS:
            result = client.post(f"/structr/rest/{CHECK}", {"type": type_name, "check": as_check(source)})
            stored = len(client.get_all(type_name)["result"])
            if result.get("count") != stored:
                raise RuntimeError(f"{type_name}: the check saw {result.get('count')} nodes, REST lists {stored}")
            print(f"    {type_name}: {stored} checked, {len(result['broken'])} breaking it")
            found += [f"{type_name} {line}" for line in result["broken"]]
        return found
    finally:
        client.delete(f"/structr/rest/SchemaMethod/{method}")


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    to_install = []
    for type_name, source in ONSAVE_TWINS:
        live = client.get("/structr/rest/SchemaMethod", params={"schemaNode": schema_node(client, type_name), "name": "onSave"})["result"]
        if not live or live[0].get("source") != source:
            to_install.append((type_name, source))

    print("[1] The stored nodes, each against its validator...")
    if to_install:
        breaches = stored_breaches(client)
        for line in breaches:
            print(f"    {line}")
        if breaches:
            print(f"FAILED: {len(breaches)} stored node(s) break their invariant; nothing was installed. An onSave would "
                  f"refuse every later edit of them: correct them first")
            sys.exit(1)
    else:
        print("    (every onSave is already installed)")

    print("[2] onSave, the onCreate validator's source...")
    for type_name, source in ONSAVE_TWINS:
        if (type_name, source) in to_install:
            client.ensure_method(schema_node(client, type_name), "onSave", source, return_raw_result=False)
        print(f"    {type_name}.onSave  installed={(type_name, source) in to_install}")
    if to_install:
        print("\nRestart Structr before trusting a check of it (hard rule 8).")


if __name__ == "__main__":
    main()
