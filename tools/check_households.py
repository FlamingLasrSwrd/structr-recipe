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
  superuser with mealplanner/pantry.py and inventory.py;
  household A's week (set up as committing a planned week will make it) is skipped with a recipe instead,
  undone and cooked by A's members, and B's member cannot touch it; A's cook draws on A's own stock only;
  a recipe asked for the same week by each household makes a week of that name for each;
  and none of them acts on what every signed-in user sees (the data made before households kept theirs
  apart): a portion expiring sooner than A's, which A's cook must not draw on and A cannot book on, a
  meal A cannot change, and a week of that name A's request must not add to.

It removes everything it made, and first sweeps what an interrupted earlier run left (sweep). Exits 1
on any failure. Needs STRUCTR_TOOLS_PASSWORD and
STRUCTR_URL, and the methods installed (tools/install_methods.py, and tools/install_pages.py for the
bookings' lock).
"""

import argparse
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import pantry
from mealplanner.connection import connect
from mealplanner.inventory import instance_expiration
from mealplanner.nutrition_scope import nutrition_report, raw_inputs, week_totals
from mealplanner.shopping import shopping_list

PRIVATE = {"visibleToAuthenticatedUsers": False, "visibleToPublicUsers": False}
SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}
WRITTEN = ("TemporalRegion", "Process", "ContainerObject", "PortionOfSubstance", "Quality", "Measurement", "Allocation",
           "MealPlan", "MealPlanEntry", "QuantitySpecification", "MealShare", "NutritionTarget")
GRANTS = ("stockOnHand", "bookPantry", "bookWeek", "bookRequest", "nutritionReport", "shoppingList", "DomainType/_id") \
    + tuple(f"{t}/_id" for t in WRITTEN)
# Run as the superuser to give household A a week of its own, as committing a planned week will (Path S
# stage 4): a dinner to cook and a lunch of its leftovers, private to A and granted to its Group
WEEK_SETUP = """{
  const p = $.methodParameters;
  const household = $.find("Household", {id: p.household}), plan = $.find("Plan", {id: p.plan});
  const hh = Array.isArray(household) ? household[0] : household, recipe = Array.isArray(plan) ? plan[0] : plan;
  const mine = (type, props) => {
    const node = $.create(type, Object.assign(props, {visibleToAuthenticatedUsers: false, visibleToPublicUsers: false}));
    $.grant(hh, node, "read, write, delete");
    return node;
  };
  const week = mine("MealPlan", {name: p.name, forHousehold: hh});
  const dinner = mine("MealPlanEntry", {name: p.name + " Dinner -- " + recipe.name, memberOf: week, isSkipped: false,
    references: recipe, hasPlannedServings: 2.0, isAbout: mine("TemporalRegion", {name: p.name + " dinner", hasBeginning: p.dinner})});
  const lunch = mine("MealPlanEntry", {name: p.name + " Lunch -- " + recipe.name, memberOf: week, isSkipped: false,
    consumesLeftoverFrom: dinner, isAbout: mine("TemporalRegion", {name: p.name + " lunch", hasBeginning: p.lunch})});
  const protein = $.find("DomainType", {name: "Protein"});
  const range = mine("QuantitySpecification", {name: p.name + " protein range", minValue: 30.0, maxValue: 200.0, unit: "g",
                                               status: "specified"});
  week.hasConstraint = [mine("NutritionTarget", {name: p.name + " protein a day", forNutrient: Array.isArray(protein) ? protein[0] : protein,
                                                 hasTargetRange: range, hasTimeScope: "daily", dayBoundaryRule: "midnight", strictness: "hard"})];
  return {week: week.id, dinner: dinner.id, lunch: lunch.id};
}"""
OPERATIONS = ("Purchase", "Use")
SHARED_TOKEN = "e0e0e0"         # the start of the token of the stock everyone sees that the check buys, so a sweep finds it


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


def sweep(client) -> int:
    """What an interrupted run left: whatever its test members own or its test households were granted,
    the weeks it names, its stock everyone sees, its setup method, and the people and households."""
    def ours(row: dict) -> bool:
        name = row.get("name") or ""
        return ((row.get("owner") or {}).get("name") or "").startswith("TEST -- member") \
            or any((g.get("name") or "").startswith("TEST -- household") for g in row.get("grantees") or []) \
            or name.startswith(("CHECK household A week", "CHECK everyone's week", f"Purchase {SHARED_TOKEN}")) \
            or name == "Week of 2099-12-28"
    gone = 0
    for type_name in WRITTEN:
        for row in client.get_all(type_name)["result"]:
            if row.get("type") == type_name and ours(row):
                try:
                    client.delete(f"/structr/rest/{type_name}/{row['id']}")
                    gone += 1
                except Exception:                     # already gone with another
                    pass
    for m in client.get("/structr/rest/SchemaMethod")["result"]:
        if m.get("name") == "testcheckhouseholdweek":
            client.delete(f"/structr/rest/SchemaMethod/{m['id']}")
            gone += 1
    for type_name, prefix in (("Household", "TEST -- household"), ("Person", "TEST -- member")):
        for row in client.get_all(type_name)["result"]:
            if (row.get("name") or "").startswith(prefix):
                client.delete(f"/structr/rest/{type_name}/{row['id']}")
                gone += 1
    return gone


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
    left = sweep(client)
    if left:
        print(f"swept {left} node(s) an interrupted earlier run left")
    try:
        m = setup(check, client)
        print("two households: A (A1, A2) and B (B1), each member signed in as themselves")
        before_shared = len(check.made)
        shared = everyones(check, client, args.food, args.keeps)
        shared_ids = {i for _, i in check.made[before_shared:]}
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

        written = [(t, i) for t, i in check.made if t in WRITTEN and i not in shared_ids]
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

        got = m["A1"].call("bookPantry", do="use", portion=shared["portion"], amount=10, unit="g", token=secrets.token_hex(4))
        check.remember(got.get("created") or [])
        if not (got.get("problem") or "").endswith("not your household's stock") or got.get("created"):
            check.fail(f"A1 using stock every signed-in user sees was not refused: {got}")
        else:
            print("  A1 cannot book on stock every signed-in user sees: not your household's stock")
        own_a = [bought["A"]] + [r["id"] for t, r in check.named(f"Purchase {token['race']} -- {args.food}") if t == "PortionOfSubstance"]
        week_check(check, client, m, args.food, args.keeps, bought, shared, own_a)
        request_check(check, client, m, shared)

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


def everyones(check: Check, client, food: str, keeps: str) -> dict:
    """What every signed-in user sees, as the data made before households kept theirs apart is: a
    portion of the food bought two days ago (so it expires before A's), a meal of a week of no
    household's, and the week a request will name. Written as the superuser, through Python."""
    token = SHARED_TOKEN + secrets.token_hex(3)
    stock = pantry.buy(client, food, 300, "g", datetime.now(timezone.utc) - timedelta(days=2), token, keeps=keeps)
    check.remember(stock.created)
    portion = [r for t, r in check.named(f"Purchase {token} -- {food}") if t == "PortionOfSubstance"][0]["id"]
    plan = next(p for p in client.get_all("Plan")["result"] if p.get("specializationOf"))
    week = check.make("MealPlan", {"name": f"CHECK everyone's week {token}", **SEEN})
    region = check.make("TemporalRegion", {"name": f"CHECK everyone's week {token} region",
                                           "hasBeginning": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000"), **SEEN})
    meal = check.make("MealPlanEntry", {"name": f"CHECK everyone's week {token} Dinner -- {plan['name']}", "memberOf": week,
                                        "isSkipped": False, "references": plan["id"], "hasPlannedServings": 2.0, "isAbout": region, **SEEN})
    asked = check.make("MealPlan", {"name": "Week of 2099-12-28", **SEEN})
    return {"portion": portion, "meal": meal, "meals_week": week, "week": asked}


def private_to(check: Check, client, m: dict, names, side: str) -> int:
    """Every node of these names private: its household's member reads it, the other household's gets a
    404, and its flags show it to no one. The number of failures."""
    fellow, other = ("A2", "B1") if side == "A" else ("B1", "A2")
    bad = 0
    for name in names:
        for type_name, row in check.named(name):
            full = client.get_all(type_name, row["id"])["result"]
            mine, theirs = m[fellow].read(type_name, row["id"]), m[other].read(type_name, row["id"])
            if (full.get("visibleToAuthenticatedUsers"), full.get("visibleToPublicUsers")) != (False, False) or mine != 200 or theirs != 404:
                bad += 1
                check.fail(f"{type_name} {name}: its household reads {mine}, the other {theirs}, "
                           f"visible to all: {full.get('visibleToAuthenticatedUsers')}")
    return bad


def week_check(check: Check, client, m: dict, food: str, keeps: str, bought: dict, shared: dict, own_a: list) -> None:
    """Household A's week through bookWeek: a member of A skips its dinner with another recipe eaten
    instead (its lunch of leftovers going with it), B's member cannot touch it, the skip is undone, and
    A's dinner is cooked from A's own stock only, B's untouched (mealplanner/menu_changes.py, pantry.cook)."""
    plans = [p for p in client.get_all("Plan")["result"] if p.get("specializationOf") and p.get("hasRecipeYield")
             and client.get_all("QuantitySpecification", p["hasRecipeYield"]["id"])["result"].get("unit") == "servings"]
    cooks = [p for p in plans if any(spec["specifies"].get("name") == food for _, spec in raw_inputs(client, p))]
    if not cooks or len(plans) < 2:
        check.fail(f"no recipe here takes {food}, or fewer than two recipes: the week is not checked")
        return
    dish = cooks[0]
    other = next(p for p in plans if p["id"] != dish["id"])
    a_household = [h for h in client.get("/structr/rest/Household", params={"name": "TEST -- household A"})["result"]][0]["id"]
    setup = check.make("SchemaMethod", {"name": "testcheckhouseholdweek", "source": WEEK_SETUP})
    begins = datetime.now(timezone.utc) + timedelta(days=1)
    name = f"CHECK household A week {secrets.token_hex(3)}"     # no " -- ": an entry's name is "<meal> -- <recipe>"
    week = client.post("/structr/rest/testcheckhouseholdweek", {"household": a_household, "plan": dish["id"], "name": name,
                       "dinner": begins.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                       "lunch": (begins + timedelta(hours=18)).strftime("%Y-%m-%dT%H:%M:%S+0000")})["result"]
    check.remember([name, f"{name} dinner", f"{name} lunch", f"{name} Dinner -- {dish['name']}", f"{name} Lunch -- {dish['name']}",
                    f"{name} protein range", f"{name} protein a day"])
    read_check(check, client, m, week["week"], food, own_a, shared["meals_week"])
    instead_name = f"{name} Dinner -- {other['name']}"

    got = m["B1"].call("bookWeek", do="skip", entry=week["dinner"], instead=other["name"], token=secrets.token_hex(4))
    check.remember(got.get("created") or [])
    if got.get("problem") != "no such meal" or got.get("created"):
        check.fail(f"B1 skipping A's dinner was not refused as no such meal: {got}")
    got = m["A1"].call("bookWeek", do="skip", entry=shared["meal"], token=secrets.token_hex(4))
    check.remember(got.get("created") or [])
    if not (got.get("problem") or "").endswith("not your household's week") \
            or client.get_all("MealPlanEntry", shared["meal"])["result"].get("isSkipped"):
        check.fail(f"A1 skipping a meal every signed-in user sees was not refused: {got}")
    else:
        print("  A1 cannot change a meal every signed-in user sees: not your household's week")
    got = m["A2"].call("bookWeek", do="skip", entry=week["dinner"], instead=other["name"], token=secrets.token_hex(4))
    check.remember(got.get("created") or [])
    dinner = client.get_all("MealPlanEntry", week["dinner"])["result"]
    lunch = client.get_all("MealPlanEntry", week["lunch"])["result"]
    if got.get("problem") or not dinner.get("isSkipped") or not lunch.get("isSkipped") or instead_name not in (got.get("created") or []):
        check.fail(f"A2 skipping A's dinner with {other['name']} instead: {got}")
    else:
        print(f"  A2 skipped A's dinner with {other['name']} instead: its lunch went with it, and the recipe instead is planned")
    got = m["A1"].call("bookWeek", do="unskip", entry=week["dinner"], token=secrets.token_hex(4))
    if not got.get("problem") or "planned at this meal now" not in got["problem"]:
        check.fail(f"A1 undoing while the recipe instead holds the dinner's time was not refused: {got}")
    instead = [r for t, r in check.named(instead_name) if t == "MealPlanEntry"]
    m["A1"].call("bookWeek", do="skip", entry=instead[0]["id"], token=secrets.token_hex(4)) if instead else None
    got = m["A1"].call("bookWeek", do="unskip", entry=week["dinner"], token=secrets.token_hex(4))
    dinner = client.get_all("MealPlanEntry", week["dinner"])["result"]
    lunch = client.get_all("MealPlanEntry", week["lunch"])["result"]
    if got.get("problem") or dinner.get("isSkipped") or lunch.get("isSkipped"):
        check.fail(f"A1 undoing the skip: {got}")
    else:
        print("  A1 undid it once the recipe instead was skipped: dinner and lunch planned again")

    before_b = pantry.on_hand(client, client.get_all("PortionOfSubstance", bought["B"])["result"], datetime.now(timezone.utc))
    token = secrets.token_hex(4)
    got = m["A1"].call("bookWeek", do="cook", entry=week["dinner"], token=token)
    check.remember(got.get("created") or [])
    drawn = [client.get_all("Allocation", r["id"])["result"] for t, r in
             (x for n in (got.get("created") or []) for x in check.named(n)) if t == "Allocation"]
    about = {(a.get("isAbout") or {}).get("id") for a in drawn}
    after_b = pantry.on_hand(client, client.get_all("PortionOfSubstance", bought["B"])["result"], datetime.now(timezone.utc))
    everyone = [i for i in about if client.get_all("PortionOfSubstance", i)["result"].get("visibleToAuthenticatedUsers")]
    if shared["portion"] in about:
        check.fail("A1's cook drew on the stock every signed-in user sees, which expires first")
    if got.get("problem") or not drawn or bought["B"] in about or everyone or abs((before_b or 0) - (after_b or 0)) > 1e-9:
        check.fail(f"A1 cooking A's dinner: {got.get('problem')}; drew from {len(about)} portion(s), B's among them: "
                   f"{bought['B'] in about}, stock all can see: {len(everyone)}; B's on hand {before_b} -> {after_b}")
    elif not client.get_all("MealPlanEntry", week["dinner"])["result"].get("fulfilledBy"):
        check.fail("A1's cook did not mark A's dinner cooked")
    else:
        print(f"  A1 cooked A's dinner from A's own stock ({len(drawn)} draw(s)), B's {before_b:g} g untouched")
    if not private_to(check, client, m, (got.get("created") or []) + [instead_name], "A"):
        print("  every node the week's bookings made is private to A")


def read_check(check: Check, client, m: dict, week_id: str, food: str, own_a: list, everyones_week: str) -> None:
    """nutritionReport and shoppingList for household A's week, as A1: Python's nutrition report for the
    week, and Python's shopping list for it with only A's own stock against the need; B1 gets neither."""
    got = m["A1"].call("nutritionReport", week=week_id)
    rows = nutrition_report(client, week_id)
    rows += week_totals(rows)
    shown = {(r["target"], r["group"]): r for r in got.get("rows") or []}
    wrong = [r for r in rows if (r["target"], r["group"]) not in shown or shown[(r["target"], r["group"])]["status"] != r["status"]
             or abs((shown[(r["target"], r["group"])].get("total") or 0) - (r.get("total") or 0)) > 1e-6]
    if got.get("problem") or not rows or len(shown) != len(rows) or wrong:
        check.fail(f"A1's nutritionReport for A's week: {got.get('problem')}; {len(shown)} groups against Python's {len(rows)}, "
                   f"{len(wrong)} differing")
    else:
        print(f"  A1's nutritionReport for A's week: {len(rows)} groups, as Python's nutrition_report")
    now = datetime.now(timezone.utc)
    own = 0.0
    for portion_id in own_a:
        portion = client.get_all("PortionOfSubstance", portion_id)["result"]
        grams, days = pantry.on_hand(client, portion, now), instance_expiration(client, portion, now)[1]
        if grams and grams > 0 and (days is None or days >= 0):
            own += grams
    listed = m["A1"].call("shoppingList", week=week_id)
    want = {line.food: line for line in shopping_list(client, week_id, now, None).to_buy + shopping_list(client, week_id, now, None).covered}
    lines = {l["food"]: l for l in (listed.get("buy") or []) + (listed.get("covered") or [])}
    line = lines.get(food)
    if listed.get("problem") or set(lines) != set(want) or line is None or abs(line["need"] - want[food].need) > 1e-6 \
            or abs(line["have"] - own) > 1e-6 or abs(line["buy"] - max(0.0, want[food].need - own)) > 1e-6:
        check.fail(f"A1's shoppingList for A's week: {listed.get('problem')}; foods {sorted(lines)} against Python's {sorted(want)}; "
                   f"{food}: {line}, Python's need {want[food].need if food in want else None}, A's own stock {own}")
    else:
        print(f"  A1's shoppingList for A's week: {food} needs {line['need']:g} g, A's own stock {own:g} g, buy {line['buy']:g} g")
    for method in ("nutritionReport", "shoppingList"):
        if m["B1"].call(method, week=week_id).get("problem") != "no such week":
            check.fail(f"B1's {method} for A's week was not refused as no such week")
        if not (m["A1"].call(method, week=everyones_week).get("problem") or "").endswith("not your household's week"):
            check.fail(f"A1's {method} for a week every signed-in user sees was not refused")


def request_check(check: Check, client, m: dict, shared: dict) -> None:
    """A recipe asked for a week through bookRequest: A1's makes household A's own week, B1's another of
    the same name for B, and neither sees the other's (mealplanner/requests.py)."""
    plans = [p for p in client.get_all("Plan")["result"] if p.get("specializationOf")][:2]
    start = "2099-12-28"
    name = f"Week of {start}"
    asked = {}
    for who, plan in (("A1", plans[0]), ("B1", plans[1])):
        got = m[who].call("bookRequest", do="ask", recipe=plan["specializationOf"]["id"], week=start, token=secrets.token_hex(4))
        check.remember(got.get("created") or [])
        asked[who[0]] = plan["specializationOf"]["id"]
        if got.get("problem"):
            check.fail(f"{who} asking for {plan['name']}: {got['problem']}")
    weeks = [w for w in client.get("/structr/rest/MealPlan", params={"name": name})["result"]
             if w.get("type") == "MealPlan" and w["id"] != shared["week"]]
    if client.get_all("MealPlan", shared["week"])["result"].get("requestsRecipe"):
        check.fail("a household's request was added to the week every signed-in user sees")
    for w in weeks:
        if ("MealPlan", w["id"]) not in check.made:
            check.made.append(("MealPlan", w["id"]))
    rows = {client.get_all("MealPlan", w["id"])["result"]["forHousehold"]["name"][-1]: client.get_all("MealPlan", w["id"])["result"]
            for w in weeks if client.get_all("MealPlan", w["id"])["result"].get("forHousehold")}
    seen = {side: {r["id"] for r in (rows.get(side) or {}).get("requestsRecipe") or []} for side in ("A", "B")}
    if len(weeks) != 2 or seen != {"A": {asked["A"]}, "B": {asked["B"]}}:
        check.fail(f"two households asking for the week of {start}: {len(weeks)} MealPlan(s), requests {seen}")
    elif m["A2"].read("MealPlan", rows["A"]["id"]) != 200 or m["A2"].read("MealPlan", rows["B"]["id"]) != 404:
        check.fail("A2 does not read A's asked-for week, or reads B's")
    else:
        print(f"  A1 and B1 each asked for a recipe in the week of {start}: two weeks of that name, one each, each "
              f"seeing only its own")
    got = m["A2"].call("bookRequest", do="withdraw", recipe=asked["A"], week=start, token=secrets.token_hex(4))
    if got.get("problem") or (client.get_all("MealPlan", rows["A"]["id"])["result"].get("requestsRecipe") if "A" in rows else None):
        check.fail(f"A2 taking back A's request: {got}")
    else:
        print("  A2 took A's request back")


if __name__ == "__main__":
    sys.exit(main())
