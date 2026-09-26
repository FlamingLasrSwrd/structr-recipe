"""Tests invariant 27a: a reservation Role on a portion and the
consumes_leftover_from edge between entries must agree (data-model.md
Sec 11; validator ROLE_ONCREATE in mealplanner/domain_invariants.py).

The commit that introduced Role.targetsEntry said it was "verified against
both a correct case (accepted) and a deliberately wrong one (rejected with
the right error token)". That verification was ad-hoc code, never committed,
so nothing a reviewer could run backed the claim. This is that check.

Setup, on the "Leftover test week" entries scripts/15e builds:
  Monday dinner cooks the braised chicken (the Process fulfills that entry),
  Wednesday lunch consumes leftovers from Monday dinner.
Cases:
  accepted  a Reservation Role on the cook's output portion, targeting the
            entry that consumes leftovers FROM the entry that cooked it
            (left in place: it is part of the fixture)
  rejected  targeting an entry that consumes no leftover at all
            -> target_entry_must_itself_consume_a_leftover
  rejected  targeting an entry that consumes leftovers from a DIFFERENT entry
            -> reservation_role_target_disagrees_with_leftover_source

Also links Monday dinner to the cooking Process (fulfilledBy), which the
live instance had but no script did.

The validator checks "when possible": if the portion has no generating
Process yet, or that Process fulfills no entry, it passes without checking.
This script establishes both before testing, so the rejections are real.

Run with: python3 scripts/16b_reservation_role_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient, StructrError

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "


def one(client, type_name, name):
    return client.get(f"/structr/rest/{type_name}", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    monday = one(client, "MealPlanEntry", f"{P}Monday dinner -- fresh braised chicken")
    wednesday = one(client, "MealPlanEntry", f"{P}Wednesday lunch -- leftover chicken")
    process = one(client, "Process", f"{P}Braised Chicken Breast cooking process")
    portion = one(client, "PortionOfSubstance", f"{P}Braised Chicken Breast output portion")
    plan = one(client, "Plan", f"{P}Braised Chicken Breast v1")
    reservation = one(client, "DomainType", "Reservation")

    print("[1] Establish the chain the validator needs: Monday dinner is fulfilled by the Process that made the portion...")
    client.patch(f"/structr/rest/MealPlanEntry/{monday}", {"fulfilledBy": process})
    made_by = client.get_all("PortionOfSubstance", portion)["result"].get("beginsToExistDuring")
    check(made_by and made_by["id"] == process, "the output portion begins to exist during that Process")
    fulfilled = client.get_all("Process", process)["result"].get("fulfillsMealPlanEntries", [])
    check([e["id"] for e in fulfilled] == [monday], "the Process fulfills exactly Monday dinner")

    made = []  # ephemeral nodes to remove afterwards

    def make_entry(name, **fields):
        node = client.upsert("MealPlanEntry", "name", name, fields)
        made.append(("MealPlanEntry", node))
        return node

    def attempt_role(name, target):
        """POST a Reservation Role; returns the validator's error text, or None if it was accepted."""
        try:
            created = client.post("/structr/rest/Role", {
                "name": name, "hasKind": reservation, "inheresIn": portion, "targetsEntry": target,
                "visibleToAuthenticatedUsers": True,
            })
        except StructrError as exc:
            return str(exc.body)
        made.append(("Role", created["result"][0]))
        return None

    try:
        print("\n[2] Accepted: a Role targeting the entry that consumes leftovers from Monday dinner...")
        # The live instance once held a Role named "...reservation role, correctly
        # targets leftover entry", created by ad-hoc code that bypassed upsert()'s
        # comma guard. targetsEntry is one-to-one, so a second Role on the same
        # entry would displace it and leave it dangling; sweep it first. Matched
        # in Python because the comma is exactly what breaks a by-name query.
        for old in client.get_all("Role")["result"]:
            if old["name"].startswith(f"{P}reservation role"):
                client.delete(f"/structr/rest/Role/{old['id']}")
        role = client.upsert("Role", "name", f"{P}reservation role for the leftover entry", {
            "hasKind": reservation, "inheresIn": portion, "targetsEntry": wednesday})
        stored = client.get_all("Role", role)["result"]
        check((stored.get("targetsEntry") or {}).get("id") == wednesday, "stored, targeting Wednesday lunch")

        print("\n[3] Rejected: a Role targeting an entry that consumes no leftover...")
        fresh_cook = make_entry(f"{P}16b decoy fresh-cook entry", references=plan, hasPlannedServings=1.0, isSkipped=False)
        error = attempt_role(f"{P}16b rejected role (target consumes no leftover)", fresh_cook)
        check(error is not None and "target_entry_must_itself_consume_a_leftover" in error,
              f"refused with the right token ({'accepted!' if error is None else error[:110]})")

        print("\n[4] Rejected: a Role targeting an entry that consumes leftovers from a DIFFERENT entry...")
        other_source = make_entry(f"{P}16b decoy source entry", references=plan, hasPlannedServings=1.0, isSkipped=False)
        other_consumer = make_entry(f"{P}16b decoy consumer of another source", consumesLeftoverFrom=other_source, isSkipped=False)
        error = attempt_role(f"{P}16b rejected role (target consumes a different source)", other_consumer)
        check(error is not None and "reservation_role_target_disagrees_with_leftover_source" in error,
              f"refused with the right token ({'accepted!' if error is None else error[:110]})")
    finally:
        for type_name, node_id in reversed(made):
            client.delete(f"/structr/rest/{type_name}/{node_id}")
        print("\n[cleanup] decoy entries (and any wrongly accepted Role) removed")

    if failures:
        print(f"\nFAILED ({len(failures)}).")
        sys.exit(1)
    print("\nAll checks passed. Invariant 27a is enforced in both directions.")


if __name__ == "__main__":
    main()
