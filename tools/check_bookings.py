"""Check that the pages book what mealplanner/pantry.py books (pages/pantry.js, pages/week.js, docs/pantry.md).

    python3 tools/check_bookings.py [--food "Chicken Breast (raw)"] [--keep]

For a development or throwaway instance only: it writes, then removes what it wrote (connect()
refuses the owner's instance; --keep leaves it for a look). Every token it books with begins with
MARK, so each run first removes whatever an earlier one left, interrupted or kept. Each booking (buy, use, count, open,
freeze, discard, a Use of the amount shown rounded up, and a planned meal cooked) is made once through
the page, as a test Person made for the run ("TEST -- booker", in no household, so the page books as the
superuser for them; signed in with a generated password that is never shown, deleted at the end), and once
through Python, naming that Person as who made it
(`by`), on two portions of the same food, and it compares:

  the nodes each wrote, field by field, the booking's token aside, who made it (wasAssociatedWith) among
  them, and that the page's Process names the Person signed in (a count's, an opening's and a move's too);
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
difference. Needs STRUCTR_TOOLS_PASSWORD and STRUCTR_URL.
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

from mealplanner import menu_changes, ownership, pantry, products, requests
from mealplanner.connection import connect
from mealplanner.inventory import FMT, instance_expiration
from mealplanner.nutrition_scope import day_zone, raw_inputs
from structr_client import StructrError

DATA = re.compile(r'<script type="application/json" id="booking-data">(.*?)</script>', re.S)
PAGE_DATA = re.compile(r'<script type="application/json" id="page-data">(.*?)</script>', re.S)
FIELDS = {     # what a booking writes on each type
    "TemporalRegion": ("hasBeginning", "hasEnd"),
    "Process": ("hasKind", "occupiesTemporalRegion", "concretizes", "wasAssociatedWith", "hasParticipant"),
    "ContainerObject": ("hasStorageCondition", "hasOpenedStatus"),
    "PortionOfSubstance": ("instanceOf", "beginsToExistDuring", "locatedIn", "hasPerishabilityType"),
    "Quality": ("hasKind", "inheresIn"),
    "Measurement": ("value", "unit", "status", "hasTime", "isAboutQuality"),
    "Allocation": ("isAbout", "hasParticipationRole", "hasActualQuantity", "process", "fulfills"),
    "MealPlanEntry": ("fulfilledBy", "isSkipped", "eatenInstead", "references", "hasPlannedServings", "isAbout", "memberOf"),
    "TypeHierarchy": (), "DomainType": ("hierarchy", "isLookupBearing", "parent"),
    "Identifier": ("identifierValue", "identifierScheme", "denotesType"), "ConceptScheme": (), "Concept": ("inScheme",),
    "DefaultSpecification": ("forType", "hasKind", "hasValue", "provenance", "source"),
    "QuantitySpecification": ("value", "unit", "status"),
}
SWEPT = (*FIELDS, "MealPlan", "MealShare", "Person", "File")   # every type the check and its bookings name
MARK = "c4ecb00c"      # begins every token the check books with; a page's own token is 8 random hex digits
# The barcodes the check adds products with: GS1 keeps the prefix 952 for demonstrations and examples, so
# no package carries one. As GTINs of 14 digits they begin 0952.
DEMO_PREFIX = "0952"
SCAN_DATA = re.compile(r'<script type="application/json" id="scan-data">(.*?)</script>', re.S)


def new_token() -> str:
    """A booking token (pages/common.js takes 4 to 16 hex digits): MARK and 8 random ones."""
    return MARK + secrets.token_hex(4)


def sweep(client) -> int:
    """Remove what an earlier run left, interrupted or with --keep: every node whose name holds MARK, which
    each booking's names and the check's own weeks carry, and then the bookings' kinds (pantry.py makes
    them on first use, and a run removes those it made) if no Process is left of any of them. How many
    were removed; RuntimeError, once every one has been tried, if Structr refused to remove any."""
    found = {}                                # id -> its own type: a supertype's query answers its subtypes too
    for type_name in SWEPT:
        for row in client.get(f"/structr/rest/{type_name}", params={"name": MARK, "_inexact": 1})["result"]:
            if MARK in (row.get("name") or ""):
                found[row["id"]] = row.get("type") or type_name
    for row in client.get("/structr/rest/Identifier", params={"identifierValue": DEMO_PREFIX, "_inexact": 1})["result"]:
        code = client.get_all("Identifier", row["id"])["result"]     # a barcode the check added, its product gone or left
        owner = (code.get("denotesType") or {}).get("name")
        if (code.get("identifierValue") or "").startswith(DEMO_PREFIX) and (owner is None or MARK in owner):
            found[code["id"]] = "Identifier"
    removed, refused = _remove(client, found)
    kinds = {row["id"]: "DomainType" for name in ownership.KINDS
             for row in client.get("/structr/rest/DomainType", params={"name": name})["result"] if row.get("type") == "DomainType"}
    if kinds and not any((p.get("hasKind") or {}).get("id") in kinds for p in client.get_all("Process")["result"]):
        kinds.update({row["id"]: "TypeHierarchy" for row in client.get("/structr/rest/TypeHierarchy",
                                                                       params={"name": pantry.OPERATIONS})["result"]})
        more, also = _remove(client, kinds)
        removed, refused = removed + more, refused + also
    if refused:
        raise RuntimeError(f"could not remove {len(refused)} node(s) an earlier run left: " + "; ".join(refused))
    return removed


def _remove(client, nodes: dict) -> tuple[int, list[str]]:
    """Delete each of `nodes` (id -> its own type): how many this removed, and a line for each Structr
    refused (a 401, a 5xx, an onSave validator's 422). One already gone, with another it hung on, Structr
    answers 404: neither (review of 2026-11-01: every failure used to count as removed)."""
    removed, refused = 0, []
    for node_id, type_name in nodes.items():
        try:
            client.delete(f"/structr/rest/{type_name}/{node_id}")
        except StructrError as exc:
            if exc.status != 404:
                refused.append(f"{type_name} {node_id}: {exc.status} {exc.body}")
            continue
        removed += 1
    return removed, refused


def remove_written(client, made: list) -> list[str]:
    """Remove what a run wrote, `made` as (type, id) in the order written, newest first, and say what
    became of it; a line for each node Structr refused to remove, which the next run's sweep tries again."""
    nodes = {node_id: type_name for type_name, node_id in reversed(made)}
    removed, refused = _remove(client, nodes)
    for line in refused:
        print(f"  could not remove {line}")
    print(f"removed {removed} of the {len(nodes)} node(s) written ({len(nodes) - removed - len(refused)} had gone with "
          f"another)" + (f"; {len(refused)} left for the next run's sweep" if refused else ""))
    return refused


SEEN = ("visibleToAuthenticatedUsers", "visibleToPublicUsers")
TIMES = ("hasBeginning", "hasTime")


class Check:
    def __init__(self, client):
        self.client, self.problems, self.made = client, [], []     # made: (type, id) to remove at the end
        self.booker = self.booker_id = None       # the test Person's session and id, for the pantry and the cook

    def sign_in_booker(self) -> None:
        """A Person made for the run, with a generated password never shown, who books the page's side."""
        name, password = f"TEST -- booker {new_token()}", secrets.token_urlsafe(18)
        self.booker_id = self.client.post("/structr/rest/Person", {"name": name, "password": password, "isAdmin": False,
                                                                   "visibleToAuthenticatedUsers": True,
                                                                   "visibleToPublicUsers": False})["result"][0]
        self.made.insert(0, ("Person", self.booker_id))          # removed last, after what names it
        self.booker = type(self.client.session)()
        self.booker.headers.update({"X-User": name, "X-Password": password})

    def booked_by_booker(self, what: str, process: str | None) -> None:
        """The page's Process names the Person signed in, and no one else."""
        rows = [row for t, row in self.nodes(process) if t == "Process"] if process else []
        who = [ref.get("id") for ref in (rows[0].get("wasAssociatedWith") or [])] if rows else None
        if who != [self.booker_id]:
            self.fail(f"{what}: the page's {process!r} names {who!r} as who made it, not the Person signed in")

    def fail(self, text: str) -> None:
        self.problems.append(text)
        print(f"  DIFFERS: {text}")

    def page(self, path: str, **params) -> dict:
        """A page's booking, as the test Person, made on the first booking (sign_in_booker)."""
        if self.booker is None:
            self.sign_in_booker()
        r = self.booker.get(f"{self.client.base_url}/structr/html/{path}", params=params, timeout=self.client.timeout)
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
            if isinstance(value, str):
                return masked(value, tokens)        # a barcode's value
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
    left = sweep(client)
    if left:
        print(f"removed {left} node(s) an earlier run left")
    check = Check(client)
    before = {name for name in (pantry.OPERATIONS, *ownership.KINDS) if check.nodes(name)}
    t = {k: new_token() for k in ("buy", "use", "count", "discard", "cook", "pybuy", "pyuse", "pycount", "open", "pyopen",
                                            "move", "pymove",
                                            "pydiscard", "pycook", "week", "stock", "menu", "pymenu", "shown",
                                            "pyshown", "recount", "pyrecount")}
    now = datetime.now(timezone.utc)
    left = []                                 # what could not be removed at the end
    try:
        print("buy")
        got = check.page("pantry", do="buy", food=args.food, amount="600", unit="g", storage="Fridge", keeps=args.keeps,
                         token=t["buy"])
        print(f"  the page could write as the superuser for anyone: {got['privileged']}")
        if got["problem"]:
            check.fail(f"buy through the page: {got['problem']}")
            return 1
        check.remember(got["created"])
        check.booked_by_booker("buy", got["process"])
        py = pantry.buy(client, args.food, 600, "g", now, t["pybuy"], storage="Fridge", keeps=args.keeps, by=check.booker_id)
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
            ("use", dict(amount="150", unit="g"), lambda tok: pantry.use(client, y_portion, 150, "g", datetime.now(timezone.utc), tok, by=check.booker_id), "use", "pyuse"),
            ("count", dict(amount="420", unit="g"), lambda tok: pantry.stock_take(client, y_portion, 420, "g", datetime.now(timezone.utc), tok, by=check.booker_id), "count", "pycount"),
            ("open", {}, lambda tok: pantry.open_portion(client, y_portion, datetime.now(timezone.utc), tok, by=check.booker_id), "open", "pyopen"),
            ("move", {"storage": "Freezer"}, lambda tok: pantry.move(client, y_portion, "Freezer", datetime.now(timezone.utc), tok, by=check.booker_id), "move", "pymove"),
        ):
            print(action)
            got = check.page("pantry", do=action, portion=p_portion, token=t[token], **page_args)
            if got["problem"]:
                check.fail(f"{action} through the page: {got['problem']}")
                continue
            check.remember(got["created"])
            check.booked_by_booker(action, got["process"])          # every booking names who made it (2026-11-23)
            py = py_call(t[py_token])
            check.remember(py.created)
            check.same_nodes(action, got["created"], [t["buy"], t[token]], py.created, [t["pybuy"], t[py_token]])
            check.same_stock(action, p_portion, y_portion)

        print("discard")
        got = check.page("pantry", do="discard", portion=p_portion, token=t["discard"])
        if got["problem"]:
            check.fail(f"discard through the page: {got['problem']}")
        else:
            check.remember(got["created"])
            check.booked_by_booker("discard", got["process"])
            py = pantry.discard(client, y_portion, datetime.now(timezone.utc), t["pydiscard"], by=check.booker_id)
            check.remember(py.created)
            check.same_nodes("discard", got["created"], [t["buy"], t["discard"]], py.created, [t["pybuy"], t["pydiscard"]])
            check.same_stock("discard", p_portion, y_portion)

        print("use the amount shown, rounded up")
        shown_check(check, client, p_portion, y_portion, t)

        print("cook")
        cook_check(check, client, t, args.food, args.keeps)

        print("add a product, and scan it")
        product_check(check, client, args.food)

        print("ask for a recipe next week")
        request_check(check, client)

        print("change the menu: skip, eat something else instead, undo")
        menu_check(check, client, t)

        print("tick the shopping list and put it into the pantry, then undo")
        bought_check(check, client, t)

        print("bookings sent at the same moment")
        race_check(check, client, args.food, args.keeps)
    finally:
        if not args.keep:
            for name in (pantry.OPERATIONS, *ownership.KINDS):
                if name not in before:
                    check.remember([name])
            left = remove_written(client, check.made)
    print("all the same" if not check.problems else f"{len(check.problems)} difference(s)")
    return 1 if check.problems or left else 0


def shown_check(check: Check, client, p_portion: str, y_portion: str, t: dict) -> None:
    """A Use of the amount the page shows, rounded up: each portion counted at 300.6 g, which shows as
    "301 g", and 301 g used through the page and through Python. Each must take all of it, 300.6 g, and
    leave nothing (pantry.USED_UP_G), where it used to be refused as more than there is."""
    for portion, token in ((p_portion, t["recount"]), (y_portion, t["pyrecount"])):
        check.remember(pantry.stock_take(client, portion, 300.6, "g", datetime.now(timezone.utc), token).created)
    got = check.page("pantry", do="use", portion=p_portion, amount="301", unit="g", token=t["shown"])
    if got["problem"]:
        check.fail(f"301 g of 300.6 g through the page: {got['problem']}")
        return
    check.remember(got["created"])
    try:
        py = pantry.use(client, y_portion, 301, "g", datetime.now(timezone.utc), t["pyshown"], by=check.booker_id)
    except pantry.PantryError as exc:
        check.fail(f"301 g of 300.6 g through Python: {exc}")
        return
    check.remember(py.created)
    check.same_nodes("use the amount shown", got["created"], [t["buy"], t["shown"]], py.created, [t["pybuy"], t["pyshown"]])
    check.same_stock("use the amount shown", p_portion, y_portion)
    drawn = [row["value"] for name in got["created"] for type_name, row in check.nodes(name) if type_name == "Measurement"]
    if drawn != [300.6]:
        check.fail(f"use the amount shown: the page drew {drawn}, not all of the 300.6 g")


def demo_barcode() -> str:
    """An EAN-13 of the demonstration prefix 952 (DEMO_PREFIX), random but for its check digit."""
    body = "952" + "".join(secrets.choice("0123456789") for _ in range(9))
    return body + str(products.check_digit(body))


def product_check(check: Check, client, food: str) -> None:
    """The pantry page's "Add a product" (pages/lib/55_products.js) against products.add_product: a product
    of `food` added through each, then a second barcode of it, the page's form sent again, and what each
    refuses alike (a barcode of the other's product, a package of another size). Then the page's barcode
    box, given each barcode, names what products.find names. The products are named with tokens and
    their barcodes are demonstration ones, so the sweep finds what an interrupted run left."""
    tok, pytok = new_token(), new_token()
    mine, theirs = f"TEST -- product {tok}", f"TEST -- product {pytok}"
    codes = [demo_barcode() for _ in range(7)]
    gtins = [products.normalize(c) for c in codes]

    def python_names(name, gtin, new=True):
        return ([name, f"{name} package size", f"{name} package size value"] if new else []) + [f"GTIN {gtin}"]

    form = dict(do="product", token=new_token(), barcode=codes[0], name=mine, food=food, amount="500", unit="g")
    got = check.page("pantry", **form)
    if got["problem"]:
        check.fail(f"add a product through the page: {got['problem']}")
        return
    check.remember(got["created"])
    py = products.add_product(client, theirs, food, codes[1], 500, "g")
    check.remember(python_names(theirs, gtins[1]))
    if py["created"] != 4:
        check.fail(f"add a product through Python: {py}")
    check.same_nodes("add a product", got["created"], [tok, gtins[0]], python_names(theirs, gtins[1]), [pytok, gtins[1]])

    offtok, offpytok = new_token(), new_token()      # a package size kept from Open Food Facts: sourced there
    off = check.page("pantry", **dict(form, token=new_token(), barcode=codes[5], name=f"TEST -- product {offtok}", source="off"))
    check.remember(off["created"])
    py = products.add_product(client, f"TEST -- product {offpytok}", food, codes[6], 500, "g", from_off=True)
    check.remember(python_names(f"TEST -- product {offpytok}", gtins[6]))
    if off["problem"] or py["created"] != 4:
        check.fail(f"add a product sized from Open Food Facts: the page said {off['problem']!r}, Python {py}")
    check.same_nodes("a product sized from Open Food Facts", off["created"], [offtok, gtins[5]],
                     python_names(f"TEST -- product {offpytok}", gtins[6]), [offpytok, gtins[6]])

    second = check.page("pantry", **dict(form, token=new_token(), barcode=codes[2]))
    check.remember(second["created"])
    py = products.add_product(client, theirs, food, codes[3], 500, "g")
    check.remember(python_names(theirs, gtins[3], new=False))
    if second["created"] != [f"GTIN {gtins[2]}"] or py["created"] != 1:
        check.fail(f"a second barcode: the page wrote {second['created']} ({second['problem']}), Python {py}")
    check.same_nodes("a second barcode", second["created"], [tok, gtins[2]], python_names(theirs, gtins[3], False), [pytok, gtins[3]])
    again = check.page("pantry", **form)
    if again["created"] or again["problem"]:
        check.fail(f"the same product sent again: wrote {again['created']}, problem {again['problem']!r}")

    for what, page_form, py_args in (
        ("a barcode of the other's product", dict(barcode=codes[1]), (theirs, food, codes[0], 500, "g")),
        ("a package of another size", dict(barcode=codes[4], amount="250"), (theirs, food, codes[4], 250, "g")),
    ):
        refused = check.page("pantry", **dict(form, token=new_token(), **page_form))
        try:
            products.add_product(client, *py_args)
            said = None
        except products.ProductError as exc:
            said = str(exc)
        a = masked(refused["problem"] or "", [tok, pytok] + gtins)
        b = masked(said or "", [pytok, tok] + gtins[1::-1] + gtins[2:])
        if refused["created"] or not refused["problem"] or said is None or a != b:
            check.fail(f"{what}: the page said {refused['problem']!r} and wrote {refused['created']}, Python said {said!r}")

    unknown = "952000000000" + str(products.check_digit("952000000000"))           # no product's
    for code in (codes[0], " ".join((gtins[0][:2], gtins[0][2:8], gtins[0][8:])), codes[3], unknown):
        r = check.booker.get(f"{client.base_url}/structr/html/pantry", params={"scan": code}, timeout=client.timeout)
        r.raise_for_status()
        shown = json.loads(SCAN_DATA.search(r.text).group(1))
        found = products.find(client, code)
        want = {"gtin": products.normalize(code), "product": found and found.product, "food": found and found.food,
                "amount": found and found.amount, "unit": found and found.unit}
        if shown != want:
            check.fail(f"scanning {code}: the page names {shown}, products.find {want}")
    print(f"  a product of {food}, one sized from Open Food Facts, and a second barcode, the same both ways; refused alike; "
          "four scans as products.find reads them")


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
    sealed = opened_statuses(client)              # a cook opens a sealed portion it leaves some of: put back after
    try:
        cooks(check, client, t, plan, week, week_name, start, make)
    finally:
        put_back(client, sealed)


def opened_statuses(client) -> dict:
    """Each container's opened status (its DomainType's id), to put back what a cook opened of the stock the
    check did not buy: a cook draws on the soonest to expire, the instance's own among it."""
    return {c["id"]: (c.get("hasOpenedStatus") or {}).get("id") for c in client.get_all("ContainerObject")["result"]}


def put_back(client, before: dict) -> None:
    now = opened_statuses(client)
    for container, status in before.items():
        if container in now and now[container] != status:
            client.patch(f"/structr/rest/ContainerObject/{container}", {"hasOpenedStatus": status})


def cooks(check: Check, client, t: dict, plan: dict, week: str, week_name: str, start: datetime, make) -> None:
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
    check.booked_by_booker("cook", got["process"])
    booking, short = pantry.cook(client, entries[1], datetime.now(timezone.utc), t["pycook"], by=check.booker_id)
    check.remember(booking.created)
    check.same_nodes("cook: its Process", [got["process"]], [t["cook"]], [booking.process], [t["pycook"]])

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


def shopping_week(check: Check, client, t: dict):
    """A week made for the check with one meal next week, of a recipe with a yield in servings that gives at
    least two foods amounts: (its id, its name), or None where there is none."""
    plans = [p for p in client.get_all("Plan")["result"] if p.get("hasRecipeYield")
             and client.get_all("QuantitySpecification", p["hasRecipeYield"]["id"])["result"].get("unit") == "servings"]
    plan = next((p for p in plans if len([s for _, s in raw_inputs(client, p) if s.get("hasSpecifiedQuantity")]) >= 2), None)
    if plan is None:
        return None
    name = f"CHECK shopping {t['week']}"

    def make(type_name, node_name, fields):
        node = client.post(f"/structr/rest/{type_name}", {"name": node_name, **fields, "visibleToAuthenticatedUsers": True,
                                                          "visibleToPublicUsers": False})["result"][0]
        check.made.append((type_name, node))
        return node

    week = make("MealPlan", name, {})
    region = make("TemporalRegion", f"{name} region", {"hasBeginning": (datetime.now(timezone.utc) + timedelta(days=8)).strftime(FMT)})
    make("MealPlanEntry", f"{name} entry", {"references": plan["id"], "hasPlannedServings": 40.0, "isAbout": region, "memberOf": week})
    return week, name


def record_of(client, name: str) -> dict | None:
    """The record an undone purchase left (a File of this name), read back, or None."""
    rows = [r for r in client.get("/structr/rest/File", params={"name": name})["result"] if r.get("type") == "File"]
    if len(rows) != 1:
        return None
    r = client.request("GET", f"/{rows[0]['id']}")
    return json.loads(r.text) if r.status_code == 200 else None


def bought_check(check: Check, client, t: dict) -> None:
    """The shopping page's "Put ticked items into the pantry" (pages/shopping.js, PANTRY_ACTIONS.bought) against
    pantry.line_purchase and buy_line, and its Undo (do=unbuy) against pantry.unbuy, on a week made for the
    check. The page's list (each line's packages, `pieces`) is compared with shopping.shopping_list first
    (check_pages). Then three lines ticked in one form: one as listed, one with other grams and another place,
    one bought as a product of its food; each booked by Python the same way, and the nodes compared. The form
    sent again books nothing. An Undo of the page's first line and pantry.unbuy of Python's delete what each
    wrote and leave the same record; an Undo of a line something has been used from is refused alike."""
    from tools import check_pages
    made = shopping_week(check, client, t)
    if made is None:
        print("  no recipe here gives two foods amounts and a yield in servings: the shopping list is not checked")
        return
    week, name = made
    problems = []
    check_pages.check_shopping(client, {"id": week, "name": name}, problems, who="the page")
    for problem in problems:
        check.fail(problem)
    r = check.booker.get(f"{client.base_url}/structr/html/shopping/{week}", timeout=client.timeout)
    r.raise_for_status()
    lines = json.loads(PAGE_DATA.search(r.text).group(1))["to_buy"]
    usable = [line for line in lines if line["pieces"] and len(line["pieces"]) <= 20]
    if len(usable) < 2:
        print(f"  the week's list has {len(usable)} line(s) to tick: the shopping list's bookings are not checked")
        return
    first, second = usable[0], usable[1]
    third = next((line for line in usable[2:] if buyable_food(client, line["food"])), None)
    product = None
    if third is not None:                     # a product of the third line's food, 400 g a package
        product = f"TEST -- product {new_token()}"
        products.add_product(client, product, third["food"], demo_barcode(), 400, "g")
        check.remember([product, f"{product} package size", f"{product} package size value"])
        check.remember([f"GTIN {code['identifierValue']}" for code in products.gtin_identifiers(client)
                        if (code.get("denotesType") or {}).get("name") == product])
    asked = [dict(food=first["food"], pieces=",".join(repr(round(g, 6)) for g in first["pieces"]), buy=repr(first["buy"])),
             dict(food=second["food"], pieces=",".join(repr(round(g, 6)) for g in second["pieces"]), buy=repr(second["buy"]),
                  grams="250", storage="Freezer")]
    if third is not None:
        asked.append(dict(food=third["food"], pieces=",".join(repr(round(g, 6)) for g in third["pieces"]), buy="900",
                          product=product))      # 900 g in 400 g packages: three
    token = new_token()[:12]                  # MARK and four more: a line's number makes 15 of the 16 a booking takes
    form = {"do": "bought", "token": token, "lines": str(len(asked))}
    for i, line in enumerate(asked):
        form[f"t{i}"] = "1"
        form.update({f"{key}{i}": value for key, value in line.items()})
    got = check.page(f"shopping/{week}", **form)
    page_tokens = [token + format(i, "03x") for i in range(len(asked))]
    py_tokens = [new_token() for _ in asked]
    now = datetime.now(timezone.utc)
    for i, line in enumerate(asked):
        booked = next((b for b in got["bookings"] if b.get("line") == i), None)
        what = f"line {i + 1} ({line['food']}" + (", other grams and place" if "grams" in line else ", a product" if "product" in line else "") + ")"
        if booked is None or booked["problem"]:
            check.fail(f"{what} through the page: {booked and booked['problem']}")
            continue
        check.remember(booked["created"])
        check.booked_by_booker(what, booked["process"])
        try:
            food, pieces = pantry.line_purchase(client, line["food"], pieces=line.get("pieces"), product=line.get("product"),
                                                count=line.get("count"), grams=line.get("grams"), buy=line.get("buy"))
            py = pantry.buy_line(client, food, pieces, now, py_tokens[i], storage=line.get("storage"), by=check.booker_id)
        except pantry.PantryError as exc:
            check.fail(f"{what} through Python: {exc}")
            continue
        check.remember(py.created)
        check.same_nodes(what, booked["created"], [page_tokens[i]], py.created, [py_tokens[i]])
        portions = [n for n in booked["created"] if n.startswith(f"Purchase {page_tokens[i]} -- ") and " container" not in n
                    and not n.endswith((" mass Quality", " mass bought"))]
        print(f"  {what}: {len(portions)} portion(s), the same both ways")
    again = check.page(f"shopping/{week}", **form)
    if any(b["created"] for b in again["bookings"]):
        check.fail(f"the same form sent again wrote {[b['created'] for b in again['bookings']]}")

    # Undo: the page's first line and Python's
    undo = check.page(f"shopping/{week}", do="unbuy", purchase=page_tokens[0], token=new_token())
    booked = undo["bookings"][0]
    try:
        py = pantry.unbuy(client, py_tokens[0], datetime.now(timezone.utc), by=check.booker_id, keep=None)
        py_record = pantry.undo_record(py_tokens[0], [], now, check.booker_id)
        py_names = py.created
    except pantry.PantryError as exc:
        check.fail(f"undo through Python: {exc}")
        return
    if booked["problem"]:
        check.fail(f"undo through the page: {booked['problem']}")
        return
    check.made.append(("File", by_name(client, "File", booked["record"])))
    if sorted(masked(n, [page_tokens[0]]) for n in booked["created"]) != sorted(masked(n, [py_tokens[0]]) for n in py_names):
        check.fail(f"undo: the page deleted {booked['created']}, Python {py_names}")
    left = [n for n in booked["created"] + py_names if check.nodes(n)]
    if left:
        check.fail(f"undo left {left}")
    record = record_of(client, booked["record"])
    if record is None:
        check.fail(f"undo: no record {booked['record']!r} to read back")
    else:
        names = sorted(masked(n["name"], [page_tokens[0]]) for n in record["nodes"])
        if names != sorted(masked(n, [page_tokens[0]]) for n in booked["created"]) or record["by"] != check.booker_id \
                or record["undone"] != f"Purchase {page_tokens[0]}" or set(py_record) != set(record):
            check.fail(f"undo: the record says {record['undone']!r} by {record['by']!r} of {names}")
        portion = next((n for n in record["nodes"] if n["type"] == "PortionOfSubstance"), None)
        if not portion or (portion.get("instanceOf") or {}).get("name") != first["food"]:
            check.fail(f"undo: the record's portion is {portion}")
    again = check.page(f"shopping/{week}", do="unbuy", purchase=page_tokens[0], token=new_token())
    if not again["bookings"][0]["problem"]:
        check.fail("undo: taking back the same purchase again was not refused")

    # an Undo is refused once something was used from the purchase
    portion = by_name(client, "PortionOfSubstance", f"Purchase {page_tokens[1]} -- {second['food']}")
    use = pantry.use(client, portion, 10, "g", datetime.now(timezone.utc), new_token())
    check.remember(use.created)
    refused = check.page(f"shopping/{week}", do="unbuy", purchase=page_tokens[1], token=new_token())["bookings"][0]
    try:
        pantry.unbuy(client, py_tokens[1], datetime.now(timezone.utc))
        said = None                            # Python's has nothing used from it: taken back, as it should be
    except pantry.PantryError as exc:
        said = str(exc)
    if not refused["problem"] or "used" not in refused["problem"] or refused["created"] or said is not None:
        check.fail(f"undo after a use: the page said {refused['problem']!r}, Python {said!r}")
    print("  undone alike, with the same record; refused once some of it was used")


def buyable_food(client, name: str) -> bool:
    """A food a product can be added below (products.add_product): a Food Identity type with no child but products."""
    rows = [r for r in client.get("/structr/rest/DomainType", params={"name": name})["result"] if r.get("type") == "DomainType"]
    if len(rows) != 1:
        return False
    food = client.get_all("DomainType", rows[0]["id"])["result"]
    ids = products.product_ids(client)
    return (food.get("hierarchy") or {}).get("name") == "Food Identity" and food["id"] not in ids \
        and all(c["id"] in ids for c in food.get("children") or [])


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
        got = check.page(f"week/{weeks['menu'][0]}", do=action, entry=entry, token=new_token(), **extra)
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
    client.get("/structr/rest/me")            # a session that has ended is opened here, before each copy takes its token

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
    token = new_token()
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
            dict(do="ask", recipe=r, week=start.isoformat(), token=new_token()) for r in recipes])]
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
        r = client.request("GET", f"/structr/html/recipe/{plan['id']}")
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
        got = check.page(f"recipe/{plan['id']}", do="ask", recipe=recipe, week=offered["week"], token=new_token())
        if got["problem"] or settled(start, before + [recipe]) != before + [recipe]:
            check.fail(f"asking through the page: {got}")
        week = requests._week(client, start)
        if week and (week.get("visibleToAuthenticatedUsers"), week.get("visibleToPublicUsers")) != (True, False):
            check.fail(f"{week['name']}: visibility not stated")
        again = check.page(f"recipe/{plan['id']}", do="ask", recipe=recipe, week=offered["week"], token=new_token())
        if again["created"] or settled(start, before + [recipe]) != before + [recipe]:
            check.fail(f"asking twice wrote again: {again}")
        if not requests.withdraw(client, recipe, start) or settled(start, before) != before:
            check.fail("requests.withdraw did not take back what the page asked for")
        if not requests.ask(client, recipe, start) or not shown()["asked"]:
            check.fail("the page does not see what requests.ask wrote")
        check.page(f"recipe/{plan['id']}", do="withdraw", recipe=recipe, week=offered["week"], token=new_token())
        if settled(start, before) != before:
            check.fail("withdrawing through the page left the request")
    finally:
        week = requests._week(client, start)
        if not existed and week is not None and not week.get("requestsRecipe"):
            client.delete(f"/structr/rest/MealPlan/{week['id']}")
    print(f"  {plan['name']}: the week of {start}, asked for and taken back both ways")


if __name__ == "__main__":
    sys.exit(main())
