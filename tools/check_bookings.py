"""Check that the pages book what mealplanner/pantry.py books (pages/pantry.js, pages/week.js, docs/pantry.md).

    python3 tools/check_bookings.py [--food "Chicken Breast (raw)"] [--keep]

For a development or throwaway instance only: it writes, then removes what it wrote (connect()
refuses the owner's instance; --keep leaves it for a look). Each booking (buy, use, count, open,
freeze, discard, and a planned meal cooked) is made once through the page, as the superuser
(Structr honours the X-User headers for pages), and once through Python, on two portions of the
same food, and it compares:

  the nodes each wrote, field by field, the booking's token aside;
  what the inventory engine then says of the two portions: grams on hand, days to expiry;
  that sending the page's form again writes nothing new.

It also says whether the page could write as the superuser for a user who is not one
($.doPrivileged), which is what lets a household member's booking through. Exits 1 on any
difference. Needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import pantry
from mealplanner.connection import connect
from mealplanner.inventory import FMT, instance_expiration
from mealplanner.nutrition_scope import raw_inputs

DATA = re.compile(r'<script type="application/json" id="booking-data">(.*?)</script>', re.S)
FIELDS = {     # what a booking writes on each type
    "TemporalRegion": ("hasBeginning",),
    "Process": ("hasKind", "occupiesTemporalRegion", "concretizes"),
    "ContainerObject": ("hasStorageCondition", "hasOpenedStatus"),
    "PortionOfSubstance": ("instanceOf", "beginsToExistDuring", "locatedIn", "hasPerishabilityType"),
    "Quality": ("hasKind", "inheresIn"),
    "Measurement": ("value", "unit", "status", "hasTime", "isAboutQuality"),
    "Allocation": ("isAbout", "hasParticipationRole", "hasActualQuantity", "process", "fulfills"),
    "MealPlanEntry": ("fulfilledBy",),
    "TypeHierarchy": (), "DomainType": ("hierarchy", "isLookupBearing"),
}
SEEN = ("visibleToAuthenticatedUsers", "visibleToPublicUsers")
TIMES = ("hasBeginning", "hasTime")


class Check:
    def __init__(self, client):
        self.client, self.problems, self.made = client, [], []     # made: (type, id) to remove at the end

    def fail(self, text: str) -> None:
        self.problems.append(text)
        print(f"  DIFFERS: {text}")

    def page(self, path: str, **params) -> dict:
        r = self.client.session.get(f"{self.client.base_url}/structr/html/{path}", params=params, timeout=self.client.timeout)
        r.raise_for_status()
        found = DATA.search(r.text)
        if not found:
            raise RuntimeError(f"/structr/html/{path}?do={params.get('do')} printed no booking data")
        return json.loads(found.group(1))

    def nodes(self, name: str) -> list[tuple[str, dict]]:
        out = []
        for type_name in FIELDS:
            for row in self.client.get(f"/structr/rest/{type_name}", params={"name": name})["result"]:
                if row.get("type") == type_name:
                    out.append((type_name, self.client.get_all(type_name, row["id"])["result"]))
        return out

    def remember(self, names) -> None:
        for name in names:
            for type_name, row in self.nodes(name):
                if (type_name, row["id"]) not in self.made:
                    self.made.append((type_name, row["id"]))

    def shape(self, type_name: str, row: dict, tokens: list) -> dict:
        def norm(value):
            if isinstance(value, dict):
                return masked(value.get("name") or value.get("id", ""), tokens)
            if isinstance(value, list):
                return sorted(norm(v) for v in value)
            return value
        out = {k: norm(row.get(k)) for k in FIELDS[type_name] + SEEN}
        for k in TIMES:
            if out.get(k):
                out[k] = datetime.strptime(out[k], FMT)
        return out

    def same_nodes(self, what: str, page_names, page_tokens: list, py_names, py_tokens: list) -> None:
        """The nodes each side's booking created, matched by name with the tokens (the booking's and the
        purchase's whose portion it is about) masked, then field by field."""
        mine = {masked(n, page_tokens): n for n in page_names if any(tok in n for tok in page_tokens)}
        theirs = {masked(n, py_tokens): n for n in py_names if any(tok in n for tok in py_tokens)}
        if set(mine) != set(theirs):
            self.fail(f"{what}: the page wrote {sorted(set(mine) - set(theirs))} that Python did not, "
                      f"and not {sorted(set(theirs) - set(mine))}")
        for name in sorted(set(mine) & set(theirs)):
            a = {t: self.shape(t, row, page_tokens) for t, row in self.nodes(mine[name])}
            b = {t: self.shape(t, row, py_tokens) for t, row in self.nodes(theirs[name])}
            for type_name in sorted(set(a) | set(b)):
                x, y = a.get(type_name), b.get(type_name)
                if x is None or y is None:
                    self.fail(f"{what}: {name} is a {type_name} on one side only")
                    continue
                for key in x:
                    if key in TIMES and x[key] and y[key]:
                        if abs((x[key] - y[key]).total_seconds()) > 120:
                            self.fail(f"{what}: {name}.{key}: page {x[key]}, Python {y[key]}")
                    elif x[key] != y[key]:
                        self.fail(f"{what}: {name}.{key}: page {x[key]!r}, Python {y[key]!r}")

    def same_stock(self, what: str, page_portion: str, py_portion: str) -> None:
        now = datetime.now(timezone.utc)
        a = self.client.get_all("PortionOfSubstance", page_portion)["result"]
        b = self.client.get_all("PortionOfSubstance", py_portion)["result"]
        grams = (pantry.on_hand(self.client, a, now), pantry.on_hand(self.client, b, now))
        days = (instance_expiration(self.client, a, now)[1], instance_expiration(self.client, b, now)[1])
        if grams[0] is None or grams[1] is None or abs(grams[0] - grams[1]) > 1e-6:
            self.fail(f"{what}: on hand {grams[0]!r} g by the page's booking, {grams[1]!r} g by Python's")
        if (days[0] is None) != (days[1] is None) or (days[0] is not None and abs(days[0] - days[1]) > 120 / 86400):
            self.fail(f"{what}: {days[0]!r} days to expiry by the page's booking, {days[1]!r} by Python's")
        print(f"  {what}: {grams[0]:g} g on hand both ways, expiry {'unknown' if days[0] is None else f'in {days[0]:.2f} days'}")


def masked(name: str, tokens: list) -> str:
    for k, token in enumerate(tokens):
        name = name.replace(token, f"<T{k}>")
    return name


def by_name(client, type_name: str, name: str) -> str:
    rows = [r for r in client.get(f"/structr/rest/{type_name}", params={"name": name})["result"] if r.get("type") == type_name]
    if len(rows) != 1:
        raise RuntimeError(f"expected one {type_name} named {name!r}, found {len(rows)}")
    return rows[0]["id"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--food", default="Chicken Breast (raw)", help="a food to buy, in grams")
    parser.add_argument("--keeps", default="Fresh Meat", help="its Perishability Class")
    parser.add_argument("--keep", action="store_true", help="leave what was written")
    args = parser.parse_args(argv)
    client = connect()                       # refuses the owner's instance: this writes and deletes
    check = Check(client)
    before = {name for name in ("Pantry Operation", "Purchase", "Use", "Discarding") if check.nodes(name)}
    t = {k: secrets.token_hex(4) for k in ("buy", "use", "count", "discard", "cook", "pybuy", "pyuse", "pycount",
                                            "pydiscard", "pycook", "week", "stock")}
    now = datetime.now(timezone.utc)
    try:
        print("buy")
        got = check.page("pantry", do="buy", food=args.food, amount="600", unit="g", storage="Fridge", keeps=args.keeps,
                         token=t["buy"])
        print(f"  the page could write as the superuser for anyone: {got['privileged']}")
        if got["problem"]:
            check.fail(f"buy through the page: {got['problem']}")
            return 1
        check.remember(got["created"])
        py = pantry.buy(client, args.food, 600, "g", now, t["pybuy"], storage="Fridge", keeps=args.keeps)
        check.remember(py.created)
        check.same_nodes("buy", got["created"], [t["buy"]], py.created, [t["pybuy"]])
        again = check.page("pantry", do="buy", food=args.food, amount="600", unit="g", storage="Fridge", keeps=args.keeps,
                           token=t["buy"])
        if again["created"]:
            check.fail(f"the same purchase sent again wrote {again['created']}")
        p_portion = by_name(client, "PortionOfSubstance", f"Purchase {t['buy']} -- {args.food}")
        y_portion = by_name(client, "PortionOfSubstance", f"Purchase {t['pybuy']} -- {args.food}")
        check.same_stock("bought", p_portion, y_portion)

        for action, page_args, py_call, token, py_token in (
            ("use", dict(amount="150", unit="g"), lambda tok: pantry.use(client, y_portion, 150, "g", datetime.now(timezone.utc), tok), "use", "pyuse"),
            ("count", dict(amount="420", unit="g"), lambda tok: pantry.stock_take(client, y_portion, 420, "g", datetime.now(timezone.utc), tok), "count", "pycount"),
        ):
            print(action)
            got = check.page("pantry", do=action, portion=p_portion, token=t[token], **page_args)
            if got["problem"]:
                check.fail(f"{action} through the page: {got['problem']}")
                continue
            check.remember(got["created"])
            py = py_call(t[py_token])
            check.remember(py.created)
            check.same_nodes(action, got["created"], [t["buy"], t[token]], py.created, [t["pybuy"], t[py_token]])
            check.same_stock(action, p_portion, y_portion)

        for action, page_args, py_call in (("open", {}, lambda: pantry.open_portion(client, y_portion)),
                                           ("move", {"storage": "Freezer"}, lambda: pantry.move(client, y_portion, "Freezer"))):
            print(action)
            got = check.page("pantry", do=action, portion=p_portion, token=secrets.token_hex(4), **page_args)
            if got["problem"]:
                check.fail(f"{action} through the page: {got['problem']}")
                continue
            py_call()
            check.same_stock(action, p_portion, y_portion)

        print("discard")
        got = check.page("pantry", do="discard", portion=p_portion, token=t["discard"])
        if got["problem"]:
            check.fail(f"discard through the page: {got['problem']}")
        else:
            check.remember(got["created"])
            py = pantry.discard(client, y_portion, datetime.now(timezone.utc), t["pydiscard"])
            check.remember(py.created)
            check.same_nodes("discard", got["created"], [t["buy"], t["discard"]], py.created, [t["pybuy"], t["pydiscard"]])
            check.same_stock("discard", p_portion, y_portion)

        print("cook")
        cook_check(check, client, t, args.food, args.keeps)
    finally:
        if not args.keep:
            for name in ("Pantry Operation", "Purchase", "Use", "Discarding"):
                if name not in before:
                    check.remember([name])
            for type_name, node_id in reversed(check.made):
                try:
                    client.delete(f"/structr/rest/{type_name}/{node_id}")
                except Exception as exc:          # already gone with another
                    print(f"  (could not remove {type_name} {node_id}: {exc})")
            print(f"removed the {len(check.made)} node(s) written")
    print("all the same" if not check.problems else f"{len(check.problems)} difference(s)")
    return 1 if check.problems else 0


def cook_check(check: Check, client, t: dict, food: str, keeps: str) -> None:
    """Two entries for one recipe, in a week made for the check: one cooked through the week page, one
    through Python. Each must draw the same grams of each food, and end fulfilled by its cook."""
    def takes_food(plan) -> bool:
        return any(spec["specifies"].get("name") == food for _, spec in raw_inputs(client, plan))

    plans = [p for p in client.get_all("Plan")["result"] if p.get("hasRecipeYield")
             and client.get_all("QuantitySpecification", p["hasRecipeYield"]["id"])["result"].get("unit") == "servings"]
    plan = next((p for p in plans if takes_food(p)), None)
    if plan is None:
        print(f"  no recipe with a yield in servings takes {food} here: the cook is not checked")
        return
    # enough for both cooks, so each draws all it needs whichever goes first
    stock = pantry.buy(client, food, 5000, "g", datetime.now(timezone.utc) - timedelta(minutes=1), t["stock"], keeps=keeps)
    check.remember(stock.created)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    week_name = f"CHECK bookings {t['week']}"

    def make(type_name, name, fields):
        node = client.post(f"/structr/rest/{type_name}", {"name": name, **fields, "visibleToAuthenticatedUsers": True,
                                                          "visibleToPublicUsers": False})["result"][0]
        check.made.append((type_name, node))
        return node

    week = make("MealPlan", week_name, {})
    entries = []
    for k in range(2):
        region = make("TemporalRegion", f"{week_name} region {k}", {"hasBeginning": start.strftime(FMT)})
        entries.append(make("MealPlanEntry", f"{week_name} entry {k}", {
            "references": plan["id"], "hasPlannedServings": 2.0, "isAbout": region, "memberOf": week}))
    got = check.page(f"week/{week}", do="cook", entry=entries[0], token=t["cook"])
    if got["problem"]:
        check.fail(f"cook through the page: {got['problem']}")
        return
    check.remember(got["created"])
    booking, short = pantry.cook(client, entries[1], datetime.now(timezone.utc), t["pycook"])
    check.remember(booking.created)

    def drawn(token: str) -> dict:
        totals = {}
        for type_name, row in [n for name in (got["created"] if token == t["cook"] else booking.created) for n in check.nodes(name)]:
            if type_name == "Allocation":
                portion = client.get_all("PortionOfSubstance", row["isAbout"]["id"])["result"]
                food = portion["instanceOf"]["name"]
                qty = client.get_all("Measurement", row["hasActualQuantity"]["id"])["result"]["value"]
                totals[food] = round(totals.get(food, 0.0) + qty, 6)
        return totals

    a, b = drawn(t["cook"]), drawn(t["pycook"])
    if a != b:
        check.fail(f"cook: the page drew {a}, Python {b}")
    page_short = sorted(n for n in got["notes"] if n.startswith("Not in the pantry"))
    if len(page_short) != len(short):
        check.fail(f"cook: the page says {page_short}, Python is short of {[s.food for s in short]}")
    for entry in entries:
        if not client.get_all("MealPlanEntry", entry)["result"].get("fulfilledBy"):
            check.fail(f"cook: entry {entry} is not fulfilled by its cook")
    again = check.page(f"week/{week}", do="cook", entry=entries[0], token=t["cook"])
    if not again["problem"] or "already cooked" not in again["problem"]:
        check.fail(f"cooking the same entry again: {again}")
    print(f"  {plan['name']}: drew {a or 'nothing'} both ways; short of {[s.food for s in short] or 'nothing'}")


if __name__ == "__main__":
    sys.exit(main())
