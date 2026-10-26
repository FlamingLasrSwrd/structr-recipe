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

It also asks for a recipe in the next week to plan from its page and takes it back, both
through the page and through mealplanner/requests.py (pages/recipe.js; data-model.md J33), and
changes a week's menu (a meal skipped with a recipe or something else eaten instead, and undone)
through the week page and through mealplanner/menu_changes.py (pages/week.js; J34).

Then it sends bookings at the same moment, as a double press or two people do (REVIEW.md round 3 #9):
one purchase form four times must make one purchase, and two recipes asked for in one week at once
must both be kept, in one MealPlan. Every check reads straight after the page answers, since a page
commits its booking before it answers.

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
import threading
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import menu_changes, pantry, requests
from mealplanner.connection import connect
from mealplanner.inventory import FMT, instance_expiration
from mealplanner.nutrition_scope import day_zone, raw_inputs

DATA = re.compile(r'<script type="application/json" id="booking-data">(.*?)</script>', re.S)
PAGE_DATA = re.compile(r'<script type="application/json" id="page-data">(.*?)</script>', re.S)
FIELDS = {     # what a booking writes on each type
    "TemporalRegion": ("hasBeginning", "hasEnd"),
    "Process": ("hasKind", "occupiesTemporalRegion", "concretizes"),
    "ContainerObject": ("hasStorageCondition", "hasOpenedStatus"),
    "PortionOfSubstance": ("instanceOf", "beginsToExistDuring", "locatedIn", "hasPerishabilityType"),
    "Quality": ("hasKind", "inheresIn"),
    "Measurement": ("value", "unit", "status", "hasTime", "isAboutQuality"),
    "Allocation": ("isAbout", "hasParticipationRole", "hasActualQuantity", "process", "fulfills"),
    "MealPlanEntry": ("fulfilledBy", "isSkipped", "eatenInstead", "references", "hasPlannedServings", "isAbout", "memberOf"),
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
                                            "pydiscard", "pycook", "week", "stock", "menu", "pymenu")}
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

        print("ask for a recipe next week")
        request_check(check, client)

        print("change the menu: skip, eat something else instead, undo")
        menu_check(check, client, t)

        print("bookings sent at the same moment")
        race_check(check, client, args.food, args.keeps)
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


def menu_check(check: Check, client, t: dict) -> None:
    """The week page's "Didn't make it" and "Undo" (pages/week.js) against mealplanner/menu_changes.py, on
    two weeks made for the check alike, a cook and a meal of its leftovers each: one changed through the
    page, one through Python. Each step must leave both weeks the same, the nodes made field by field."""
    plans = [p for p in client.get_all("Plan")["result"] if p.get("specializationOf")]
    if len(plans) < 2:
        check.fail("fewer than two recipes with a RecipeIdentity: the menu change is not checked")
        return
    dish, other = plans[0], plans[1]
    begins = datetime.now(timezone.utc) + timedelta(days=1)

    def make(type_name, name, fields):
        node = client.post(f"/structr/rest/{type_name}", {"name": name, **fields, "visibleToAuthenticatedUsers": True,
                                                          "visibleToPublicUsers": False})["result"][0]
        check.made.append((type_name, node))
        return node

    weeks = {}
    for side in ("menu", "pymenu"):
        name = f"CHECK menu {t[side]}"
        week = make("MealPlan", name, {})
        dinner_at = make("TemporalRegion", f"{name} dinner region", {"hasBeginning": begins.strftime(FMT),
                                                                      "hasEnd": (begins + timedelta(hours=1)).strftime(FMT)})
        lunch_at = make("TemporalRegion", f"{name} lunch region", {"hasBeginning": (begins + timedelta(hours=18)).strftime(FMT)})
        dinner = make("MealPlanEntry", f"{name} Dinner -- {dish['name']}", {
            "memberOf": week, "isSkipped": False, "references": dish["id"], "hasPlannedServings": 2.0, "isAbout": dinner_at})
        lunch = make("MealPlanEntry", f"{name} Lunch -- {dish['name']}", {
            "memberOf": week, "isSkipped": False, "consumesLeftoverFrom": dinner, "isAbout": lunch_at})
        weeks[side] = (week, dinner, lunch)

    def page(action, entry, **extra):
        got = check.page(f"week/{weeks['menu'][0]}", do=action, entry=entry, token=secrets.token_hex(4), **extra)
        check.remember(got["created"])
        return got

    def python(call, *args):
        try:
            change = call(client, *args)
        except menu_changes.MenuError as exc:
            return str(exc)
        check.remember(change.created)
        return None

    def same(step: str) -> None:
        for k in (1, 2):
            a = check.shape("MealPlanEntry", client.get_all("MealPlanEntry", weeks["menu"][k])["result"], [t["menu"]])
            b = check.shape("MealPlanEntry", client.get_all("MealPlanEntry", weeks["pymenu"][k])["result"], [t["pymenu"]])
            if a != b:
                check.fail(f"{step}: {'dinner' if k == 1 else 'lunch'}: page {a}, Python {b}")

    _, p_dinner, p_lunch = weeks["menu"]
    _, y_dinner, y_lunch = weeks["pymenu"]
    got = page("skip", p_dinner, instead=other["name"].lower())
    py = python(menu_changes.skip, y_dinner, other["name"].lower())
    if got["problem"] or py:
        check.fail(f"skip, {other['name']} instead: page {got['problem']!r}, Python {py!r}")
    same("skip, a recipe instead")
    made = f"CHECK menu {{}} Dinner -- {other['name']}"
    check.same_nodes("the meal planned instead", [made.format(t["menu"]), made.format(t["menu"]) + " region"], [t["menu"]],
                     [made.format(t["pymenu"]), made.format(t["pymenu"]) + " region"], [t["pymenu"]])
    got, py = page("unskip", p_dinner), python(menu_changes.unskip, y_dinner)
    if not got["problem"] or not py or "planned at this meal now" not in got["problem"]:
        check.fail(f"undo while the meal instead holds its time: page {got['problem']!r}, Python {py!r}")
    page("skip", _by_name(client, made.format(t["menu"])))
    python(menu_changes.skip, _by_name(client, made.format(t["pymenu"])))
    got, py = page("unskip", p_dinner), python(menu_changes.unskip, y_dinner)
    if got["problem"] or py:
        check.fail(f"undo: page {got['problem']!r}, Python {py!r}")
    same("undo")
    got, py = page("skip", p_dinner, instead="takeout"), python(menu_changes.skip, y_dinner, "takeout")
    same("skip, something else instead")
    got, py = page("unskip", p_lunch), python(menu_changes.unskip, y_lunch)
    if not got["problem"] or not py:
        check.fail(f"undo of a meal whose leftovers were never made: page {got['problem']!r}, Python {py!r}")
    print(f"  {dish['name']}: skipped with {other['name']} instead, undone, skipped with takeout instead: the same both ways")


def at_once(client, path: str, forms: list) -> list[str]:
    """Each form sent to the page at the same moment, each on a connection of its own: the answers."""
    ready, answers = threading.Barrier(len(forms)), [None] * len(forms)

    def send(i):
        session = type(client.session)()
        session.headers.update(client.session.headers)
        ready.wait()
        r = session.get(f"{client.base_url}/structr/html/{path}", params=forms[i], timeout=client.timeout)
        r.raise_for_status()
        answers[i] = r.text
    threads = [threading.Thread(target=send, args=(i,)) for i in range(len(forms))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if None in answers:
        raise RuntimeError(f"/structr/html/{path}: a request sent at once got no answer")
    return answers


def race_check(check: Check, client, food: str, keeps: str) -> None:
    """Bookings sent at the same moment (pages/common.js runBooking). Before the bookings' lock, four
    presses of one purchase made four Processes of one name, and two people asking for recipes could
    each make the week's MealPlan, or the one write over the other's list."""
    token = secrets.token_hex(4)
    form = dict(do="buy", food=food, amount="600", unit="g", storage="Fridge", keeps=keeps, token=token)
    answers = at_once(client, "pantry", [form] * 4)
    told = [json.loads(DATA.search(a).group(1)) for a in answers]
    for got in told:
        check.remember(got["created"])
    check.remember([f"Purchase {token}"])
    purchases = [type_name for type_name, _ in check.nodes(f"Purchase {token}")]
    booked = sum(1 for got in told if got["created"])
    if purchases != ["Process"] or booked != 1 or any(got["problem"] for got in told):
        check.fail(f"one purchase sent four times at once: {purchases.count('Process')} Process(es) of its name, "
                   f"{booked} page(s) said they booked it, problems {[got['problem'] for got in told if got['problem']]}")
    portion = f"Purchase {token} -- {food}"
    unseen = sum(1 for a in answers if portion not in {row["portion"] for row in json.loads(PAGE_DATA.search(a).group(1))})
    if unseen:
        check.fail(f"{unseen} of the four pages did not show the purchase they answered for")

    plans = [p for p in client.get_all("Plan")["result"] if p.get("specializationOf")][:2]
    if len(plans) < 2:
        check.fail("fewer than two recipes with a RecipeIdentity: asking at once is not checked")
        return
    start = date(2099, 12, 28)                # a week nothing else plans
    name = requests.WEEK_NAME.format(start.isoformat())
    if requests._week(client, start) is not None:
        check.fail(f"{name} exists already: asking at once is not checked")
        return
    recipes = [p["specializationOf"]["id"] for p in plans]
    try:
        told = [json.loads(DATA.search(a).group(1)) for a in at_once(client, f"recipe/{plans[0]['id']}", [
            dict(do="ask", recipe=r, week=start.isoformat(), token=secrets.token_hex(4)) for r in recipes])]
        weeks = [r for r in client.get("/structr/rest/MealPlan", params={"name": name})["result"] if r.get("type") == "MealPlan"]
        asked = sorted(r["id"] for r in requests.requested(client, start)) if len(weeks) == 1 else None
        if len(weeks) != 1 or asked != sorted(recipes) or any(got["problem"] for got in told):
            check.fail(f"two recipes asked for in one week at once: {len(weeks)} MealPlan(s) named {name}, asked {asked}, "
                       f"problems {[got['problem'] for got in told if got['problem']]}")
    finally:
        for week in client.get("/structr/rest/MealPlan", params={"name": name})["result"]:
            if week.get("type") == "MealPlan":
                client.delete(f"/structr/rest/MealPlan/{week['id']}")
    print(f"  one purchase sent four times: {purchases.count('Process')} made, {booked} said so; "
          f"two recipes asked for at once: {len(weeks)} week, {len(asked or [])} kept")


def _by_name(client, name: str) -> str:
    (row,) = [r for r in client.get("/structr/rest/MealPlanEntry", params={"name": name})["result"] if r.get("type") == "MealPlanEntry"]
    return row["id"]


def request_check(check: Check, client) -> None:
    """The recipe page's "Cook in the week of ..." (pages/recipe.js) against mealplanner/requests.py:
    the week it offers, the request it writes and takes back, and that asking twice writes nothing."""
    plan = next((p for p in client.get_all("Plan")["result"] if p.get("specializationOf")), None)
    if plan is None:
        check.fail("no recipe with a RecipeIdentity to ask for")
        return
    recipe = plan["specializationOf"]["id"]

    def shown() -> dict:
        r = client.session.get(f"{client.base_url}/structr/html/recipe/{plan['id']}", timeout=client.timeout)
        r.raise_for_status()
        return json.loads(PAGE_DATA.search(r.text).group(1))["request"]

    def settled(start, want: list) -> list:
        """The week's requests, read as soon as the page has answered."""
        return [r["id"] for r in requests.requested(client, start)]

    weeks = sorted((w for w in client.get_all("MealPlan")["result"] if w.get("hasEntry") and requests.week_start(w)),
                   key=requests.week_start)
    zone = None                       # today is the latest week's local day, as pages/common.js weekZone has it
    for c in (weeks[-1].get("hasConstraint") or []) if weeks else []:
        if c["type"] == "NutritionTarget" and zone is None:
            zone = day_zone(client.get_all("NutritionTarget", c["id"])["result"].get("dayBoundaryRule"))
    offered = shown()
    start = date.fromisoformat(offered["week"])
    expected = requests.next_week_start(client, datetime.now(zone or timezone.utc).date())
    if start != expected:
        check.fail(f"the page offers the week of {start}, requests.next_week_start {expected}")
    existed = requests._week(client, start) is not None
    before = [r["id"] for r in requests.requested(client, start)]
    if recipe in before:
        print(f"  {plan['name']} is asked for that week already; left alone")
        return
    try:
        got = check.page(f"recipe/{plan['id']}", do="ask", recipe=recipe, week=offered["week"], token=secrets.token_hex(4))
        if got["problem"] or settled(start, before + [recipe]) != before + [recipe]:
            check.fail(f"asking through the page: {got}")
        week = requests._week(client, start)
        if week and (week.get("visibleToAuthenticatedUsers"), week.get("visibleToPublicUsers")) != (True, False):
            check.fail(f"{week['name']}: visibility not stated")
        again = check.page(f"recipe/{plan['id']}", do="ask", recipe=recipe, week=offered["week"], token=secrets.token_hex(4))
        if again["created"] or settled(start, before + [recipe]) != before + [recipe]:
            check.fail(f"asking twice wrote again: {again}")
        if not requests.withdraw(client, recipe, start) or settled(start, before) != before:
            check.fail("requests.withdraw did not take back what the page asked for")
        if not requests.ask(client, recipe, start) or not shown()["asked"]:
            check.fail("the page does not see what requests.ask wrote")
        check.page(f"recipe/{plan['id']}", do="withdraw", recipe=recipe, week=offered["week"], token=secrets.token_hex(4))
        if settled(start, before) != before:
            check.fail("withdrawing through the page left the request")
    finally:
        week = requests._week(client, start)
        if not existed and week is not None and not week.get("requestsRecipe"):
            client.delete(f"/structr/rest/MealPlan/{week['id']}")
    print(f"  {plan['name']}: the week of {start}, asked for and taken back both ways")


if __name__ == "__main__":
    sys.exit(main())
