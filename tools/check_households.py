"""The gate of Path S (docs/architecture-decision.md §7a, stage 2): households that book and read as
themselves, through the Structr methods (methods/), kept apart by Structr's own access control.

    python3 tools/check_households.py [--food "Chicken Breast (raw)"] [--keeps "Fresh Meat"]

For a development or throwaway instance only: connect() refuses the owner's. It makes two test
households, "TEST -- household A" with two members and "TEST -- household B" with one, each member a
Person who signs in with a generated password that is never shown; the grants members need to call
the methods and to read a node by id; and, where missing, the shared pantry operations a household's
booking may not make itself. Then, each member as themselves:

  A1 and B1 each buy the food through bookPantry, and A1 uses some of A's;
  one purchase sent four times at once makes one, as the pages' bookings do;
  A2, in A1's household, sees A's portion through stockOnHand and B1 does not;
  B1 cannot use A's portion ("no such portion"), and nothing is written;
  every node the bookings made is private: a member of its household reads it by id, a member of the
  other gets a 404, and it is visible to no one else;
  a member cannot change shared vocabulary (a 403, and it stays as it was);
  stockOnHand's grams and days to expiry for each household's portion are Python's, worked out as the
  superuser with mealplanner/pantry.py and inventory.py.

It removes everything it made. Exits 1 on any failure. Needs STRUCTR_SUPERUSER_PASSWORD and
STRUCTR_URL, and the methods installed (tools/install_methods.py, and tools/install_pages.py for the
bookings' lock).
"""

import argparse
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import pantry
from mealplanner.connection import connect
from mealplanner.inventory import instance_expiration

PRIVATE = {"visibleToAuthenticatedUsers": False, "visibleToPublicUsers": False}
SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}
WRITTEN = ("TemporalRegion", "Process", "ContainerObject", "PortionOfSubstance", "Quality", "Measurement", "Allocation")
GRANTS = ("stockOnHand", "bookPantry", "DomainType/_id") + tuple(f"{t}/_id" for t in WRITTEN)
OPERATIONS = ("Purchase", "Use")


class Check:
    def __init__(self, client):
        self.client, self.problems = client, []
        self.made = []                                   # (type, id), removed at the end in reverse

    def fail(self, text: str) -> None:
        self.problems.append(text)
        print(f"  FAILS: {text}")

    def make(self, type_name: str, fields: dict) -> str:
        node = self.client.post(f"/structr/rest/{type_name}", fields)["result"][0]
        self.made.append((type_name, node))
        return node

    def named(self, name: str) -> list[tuple[str, dict]]:
        out = []
        for type_name in WRITTEN:
            for row in self.client.get(f"/structr/rest/{type_name}", params={"name": name})["result"]:
                if row.get("type") == type_name:
                    out.append((type_name, row))
        return out

    def remember(self, names) -> None:
        for name in names:
            for type_name, row in self.named(name):
                if (type_name, row["id"]) not in self.made:
                    self.made.append((type_name, row["id"]))


class Member:
    """A Person signed in as themselves, with X-User and X-Password, on a session of their own."""

    def __init__(self, client, name: str, password: str):
        self.client, self.name = client, name
        self.session = type(client.session)()
        self.session.headers.update({"X-User": name, "X-Password": password})

    def call(self, method: str, **arguments):
        r = self.session.post(f"{self.client.base_url}/structr/rest/{method}", json=arguments, timeout=self.client.timeout)
        if not r.ok:
            raise RuntimeError(f"{self.name}: {method} answered {r.status_code}: {r.text[:200]}")
        return r.json()["result"]

    def read(self, type_name: str, node_id: str) -> int:
        return self.session.get(f"{self.client.base_url}/structr/rest/{type_name}/{node_id}", timeout=self.client.timeout).status_code


def at_once(member: Member, method: str, arguments: dict, n: int) -> list:
    ready, answers = threading.Barrier(n), [None] * n

    def send(i):
        other = Member(member.client, member.name, member.session.headers["X-Password"])
        ready.wait()
        answers[i] = other.call(method, **arguments)
    threads = [threading.Thread(target=send, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if None in answers:
        raise RuntimeError(f"{method} sent at once: a call got no answer")
    return answers


def setup(check: Check, client) -> dict:
    """The households, their members and the grants they need; the shared operations, if missing."""
    members = {}
    for household, people in (("A", ("A1", "A2")), ("B", ("B1",))):
        ids = []
        for who in people:
            name, password = f"TEST -- member {who}", secrets.token_urlsafe(18)    # a throwaway account, never shown
            ids.append(check.make("Person", {"name": name, "password": password, "isAdmin": False, **PRIVATE}))
            members[who] = Member(client, name, password)
        check.make("Household", {"name": f"TEST -- household {household}", "members": ids, **PRIVATE})
    for signature in GRANTS:
        if not client.get("/structr/rest/ResourceAccess", params={"signature": signature})["result"]:
            check.make("ResourceAccess", {"signature": signature, "flags": 255, **SEEN})
    hierarchy = [h for h in client.get("/structr/rest/TypeHierarchy", params={"name": "Pantry Operation"})["result"] if h.get("type") == "TypeHierarchy"]
    hierarchy = hierarchy[0]["id"] if hierarchy else check.make("TypeHierarchy", {"name": "Pantry Operation", **SEEN})
    for kind in OPERATIONS:
        if not [d for d in client.get("/structr/rest/DomainType", params={"name": kind})["result"] if d.get("type") == "DomainType"]:
            check.make("DomainType", {"name": kind, "hierarchy": hierarchy, "isLookupBearing": False, **SEEN})
    return members


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--food", default="Chicken Breast (raw)", help="a food to buy, in grams")
    parser.add_argument("--keeps", default="Fresh Meat", help="its Perishability Class")
    args = parser.parse_args(argv)
    client = connect()                       # refuses the owner's instance: this writes and deletes
    check = Check(client)
    try:
        m = setup(check, client)
        print("two households: A (A1, A2) and B (B1), each member signed in as themselves")
        token = {k: secrets.token_hex(4) for k in ("a", "b", "use", "steal", "race")}
        bought = {}
        for who, key, grams in (("A1", "a", 600), ("B1", "b", 450)):
            got = m[who].call("bookPantry", do="buy", food=args.food, amount=grams, unit="g", storage="Fridge",
                              keeps=args.keeps, token=token[key])
            check.remember(got.get("created") or [])
            if got.get("problem") or not got.get("created"):
                check.fail(f"{who}'s purchase: {got}")
                return 1
            portion = [r for t, r in check.named(f"Purchase {token[key]} -- {args.food}") if t == "PortionOfSubstance"]
            bought[who[0]] = portion[0]["id"]
        print(f"  A1 bought 600 g and B1 450 g of {args.food}, as themselves")

        got = m["A1"].call("bookPantry", do="use", portion=bought["A"], amount=150, unit="g", token=token["use"])
        check.remember(got.get("created") or [])
        if got.get("problem"):
            check.fail(f"A1 using 150 g of A's: {got['problem']}")
        got = m["B1"].call("bookPantry", do="use", portion=bought["A"], amount=100, unit="g", token=token["steal"])
        check.remember(got.get("created") or [])                         # if it wrongly booked, it is removed too
        if got.get("problem") != "no such portion" or got.get("created") or check.named(f"Use {token['steal']}"):
            check.fail(f"B1 using A's portion was not refused as no such portion: {got}")
        else:
            print("  B1 cannot use A's portion: no such portion, and nothing written")

        answers = at_once(m["A1"], "bookPantry", dict(do="buy", food=args.food, amount=100, unit="g", storage="Fridge",
                                                      keeps=args.keeps, token=token["race"]), 4)
        for got in answers:
            check.remember(got.get("created") or [])
        check.remember([f"Purchase {token['race']}"])
        processes = [t for t, _ in check.named(f"Purchase {token['race']}")].count("Process")
        booked = sum(1 for got in answers if got.get("created"))
        if processes != 1 or booked != 1 or any(got.get("problem") for got in answers):
            check.fail(f"one purchase sent four times at once: {processes} Process(es), {booked} said they booked it")
        else:
            print("  one purchase sent four times at once by A1: one made, one said so")

        for who, mine, theirs in (("A2", "A", "B"), ("B1", "B", "A")):
            t0 = time.time()
            seen = {row["id"] for row in m[who].call("stockOnHand")}
            took = time.time() - t0
            if bought[mine] not in seen or bought[theirs] in seen:
                check.fail(f"{who}'s stockOnHand: own portion {'seen' if bought[mine] in seen else 'missing'}, "
                           f"the other household's {'seen' if bought[theirs] in seen else 'not seen'}")
            else:
                print(f"  {who} sees their household's portion and not the other's ({len(seen)} portions, {took:.1f} s)")

        written = [(t, i) for t, i in check.made if t in WRITTEN]
        side_of = {token["a"]: "A", token["use"]: "A", token["race"]: "A", token["b"]: "B"}    # each booking's household
        leaks = 0
        for type_name, node_id in written:
            row = client.get_all(type_name, node_id)["result"]
            side = next((s for tok, s in side_of.items() if tok in (row.get("name") or "")), None)
            fellow, other = ("A2", "B1") if side == "A" else ("B1", "A2")
            if (row.get("visibleToAuthenticatedUsers"), row.get("visibleToPublicUsers")) != (False, False):
                leaks += 1
                check.fail(f"{type_name} {row.get('name')}: visible to every signed-in user")
            mine, theirs = m[fellow].read(type_name, node_id), m[other].read(type_name, node_id)
            if side is None or mine != 200 or theirs != 404:
                leaks += 1
                check.fail(f"{type_name} {row.get('name')}: its household's member reads {mine}, the other household's {theirs}")
        if not leaks:
            print(f"  all {len(written)} nodes the bookings made are private: their household reads each, the other gets a 404")

        mass = [d for d in client.get("/structr/rest/DomainType", params={"name": "Mass"})["result"] if d.get("type") == "DomainType"][0]
        before = client.get_all("DomainType", mass["id"])["result"].get("isLookupBearing")
        status = m["A1"].session.put(f"{client.base_url}/structr/rest/DomainType/{mass['id']}",
                                     json={"isLookupBearing": not before}, timeout=client.timeout).status_code
        after = client.get_all("DomainType", mass["id"])["result"].get("isLookupBearing")
        if after != before:
            client.patch(f"/structr/rest/DomainType/{mass['id']}", {"isLookupBearing": before})
            check.fail("A1 changed the shared DomainType Mass (put back)")
        elif status != 403:
            check.fail(f"A1 changing shared vocabulary answered {status}, not 403")
        else:
            print("  A1 cannot change shared vocabulary (403, unchanged)")

        now = datetime.now(timezone.utc)
        rows = {row["id"]: row for who in ("A1", "B1") for row in m[who].call("stockOnHand")}
        for side, portion_id in bought.items():
            portion = client.get_all("PortionOfSubstance", portion_id)["result"]
            grams, days = pantry.on_hand(client, portion, now), instance_expiration(client, portion, now)[1]
            row = rows.get(portion_id) or {}
            if row.get("grams") is None or grams is None or abs(row["grams"] - grams) > 1e-6 \
                    or (days is None) != (row.get("days") is None) or (days is not None and abs(row["days"] - days) > 120 / 86400):
                check.fail(f"household {side}'s portion: stockOnHand {row.get('grams')} g, {row.get('days')} days; Python {grams} g, {days} days")
            else:
                print(f"  household {side}'s portion: {grams:g} g and {days:.2f} days to expiry, by the method and by Python")
    finally:
        for type_name, node_id in reversed(check.made):
            try:
                client.delete(f"/structr/rest/{type_name}/{node_id}")
            except Exception as exc:                      # already gone with another
                print(f"  (could not remove {type_name} {node_id}: {exc})")
        print(f"removed the {len(check.made)} node(s) made")
    print("households kept apart" if not check.problems else f"{len(check.problems)} failure(s)")
    return 1 if check.problems else 0


if __name__ == "__main__":
    sys.exit(main())
