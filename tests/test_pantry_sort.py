"""The pantry page's sorting and its Kept column (pages/pantry.js; the owner's request of 2026-11-23: "Pantry should
be sortable: by item name, expiration, and pantry location"). The whole page runs in node or gjs, where either is
installed, over a stand-in graph, as tests/test_pantry_buy_unit.py runs it; on an instance tools/check_pages.py
compares what it shows with Python, and that every order shows the same rows.

Six portions, each weighed once, so its shelf life counts from that weighing (inventory.instance_expiration).
Worked out by hand from the shelf lives below (sealed, keyed by where it is kept):

    apples    in the fridge   (fridge 21 days)                bought 5 days ago   16 days left
    Bread     in the pantry   (pantry 5 days)                 bought 1 day ago     4 days left
    chicken   in the freezer  (fridge 2, freezer 270)         bought 10 days ago 260 days left
    Milk      in the fridge   (fridge 7)                      bought 2 days ago    5 days left
    Rice      in no container (pantry 730, fridge 180)        bought 30 days ago 700 days left: kept where it
              keeps longest, the pantry, and marked assumed (inventory.assumed_storage, J31)
    Zucchini  in the fridge   (no shelf life)                 unknown, so last in every order by use-by date

The names mix lower and upper case, so a sort by character code (Z before a) would put them wrong.
"""

import json
import re
import unittest

from tests.test_pantry_buy_unit import page_code
from tools.pantry import sort_rows
from tests.test_signed_out import ENGINE, javascript

GRAPH = r"""
var N = {}, seq = 0;
function node(type, name, props) {
  var n = Object.assign({id: "id" + (++seq), type: type, name: name, defaultSpecifications: [], children: []}, props || {});
  (N[type] = N[type] || []).push(n); return n;
}
var $ = {request: REQUEST, me: {name: "Jamie"}, current: null, out: "",
  find: function (type, f) { return (N[type] || []).filter(function (n) { return !f || Object.keys(f).every(function (k) { return n[k] === f[k]; }); }); },
  print: function (s) { $.out += s; }};
var food = node("TypeHierarchy", "Food Identity", {domainTypes: []});
var SHELF = node("DomainType", "ShelfLife"), MASS = node("DomainType", "Mass");
var where = {Fridge: node("DomainType", "Fridge"), Freezer: node("DomainType", "Freezer"), Pantry: node("DomainType", "Pantry")};
node("DomainType", "Sealed"); node("DomainType", "Opened");
var DAY = 86400e3;
function portion(name, lives, kept, daysAgo) {
  var t = node("DomainType", name, {hierarchy: food, parent: null});
  food.domainTypes.push(t);
  Object.keys(lives).forEach(function (s) {
    t.defaultSpecifications.push(node("DefaultSpecification", name + " " + s, {hasKind: SHELF, keyedBy: [where[s]],
                                                                             hasValue: {value: lives[s], unit: "days"}}));
  });
  var box = kept ? node("ContainerObject", name + " box", {hasStorageCondition: where[kept], hasOpenedStatus: {name: "Sealed"}}) : null;
  var weighing = {status: "observed", value: 500, unit: "g", hasTime: new Date(Date.now() - daysAgo * DAY).toISOString()};
  node("PortionOfSubstance", "TEST -- " + name, {instanceOf: t, locatedIn: box, allocationsAbout: [],
                                                 bearerOf: [{type: "Quality", hasKind: MASS, measurements: [weighing]}]});
}
portion("apples", {Fridge: 21}, "Fridge", 5);
portion("Bread", {Pantry: 5}, "Pantry", 1);
portion("chicken", {Fridge: 2, Freezer: 270}, "Freezer", 10);
portion("Milk", {Fridge: 7}, "Fridge", 2);
portion("Rice", {Pantry: 730, Fridge: 180}, null, 30);
portion("Zucchini", {}, "Fridge", 1);
"""

A, B, C, D, E, F = (f"TEST -- {n}" for n in ("apples", "Bread", "chicken", "Milk", "Rice", "Zucchini"))


def page(**request) -> str:
    code = GRAPH.replace("REQUEST", json.dumps(request)) + "\n" + page_code()
    return javascript("var result = (function () {\n" + code + "\nreturn $.out; })();")


def rows(html: str) -> list[dict]:
    return json.loads(re.search(r'id="page-data">(.*?)</script>', html, re.S).group(1))


def order(html: str) -> list[str]:
    return [r["portion"] for r in rows(html)]


@unittest.skipUnless(ENGINE, "needs node or gjs")
class Sorting(unittest.TestCase):
    def test_by_use_by_date_soonest_first_is_the_default(self):
        html = page()
        self.assertEqual(order(html), [B, D, A, C, E, F])
        self.assertEqual([round(r["days"]) if r["days"] is not None else None for r in rows(html)], [4, 5, 16, 260, 700, None])
        self.assertIn("sorted by use-by date, soonest first", html)
        self.assertEqual(order(page(sort="expires")), [B, D, A, C, E, F])

    def test_by_use_by_date_reversed_keeps_the_unknown_last(self):
        self.assertEqual(order(page(sort="-expires")), [E, C, A, D, B, F])

    def test_by_name_ignores_case(self):
        self.assertEqual(order(page(sort="food")), [A, B, C, D, E, F])
        self.assertEqual(order(page(sort="-food")), [F, E, D, C, B, A])

    def test_by_where_it_is_kept_then_use_by_date(self):
        self.assertEqual(order(page(sort="kept")), [D, A, F, C, B, E])        # fridge, freezer, pantry
        self.assertEqual(order(page(sort="-kept")), [B, E, C, D, A, F])       # pantry first; ties still soonest first

    def test_an_order_it_does_not_know_is_the_default(self):
        for asked in ("price", "-", "--food", "food-", "<b>"):
            self.assertEqual(order(page(sort=asked)), [B, D, A, C, E, F], asked)

    def test_every_order_shows_the_same_rows(self):
        def shown(html):        # each page reads the clock again, so its days are compared to the hour
            return sorted(json.dumps(dict(r, days=None if r["days"] is None else round(r["days"] * 24))) for r in rows(html))
        default = shown(page())
        for asked in ("food", "-food", "kept", "-kept", "-expires"):
            self.assertEqual(shown(page(sort=asked)), default, asked)


@unittest.skipUnless(ENGINE, "needs node or gjs")
class Headings(unittest.TestCase):
    def heads(self, html: str) -> dict:
        return {label: (href, arrow.strip()) for href, label, arrow in
                re.findall(r'<th[^>]*><a href="([^"]*)"[^>]*>([^<]*)</a>([^<]*)</th>', html)}

    def test_each_links_to_its_order_and_the_chosen_one_to_its_reverse(self):
        self.assertEqual(self.heads(page()), {"Food": ("/structr/html/pantry?sort=food", ""),
                                              "Kept": ("/structr/html/pantry?sort=kept", ""),
                                              "Use by": ("/structr/html/pantry?sort=-expires", "▼")})
        self.assertEqual(self.heads(page(sort="food"))["Food"], ("/structr/html/pantry?sort=-food", "▼"))
        self.assertEqual(self.heads(page(sort="-food"))["Food"], ("/structr/html/pantry?sort=food", "▲"))
        self.assertEqual(self.heads(page(sort="-expires"))["Use by"], ("/structr/html/pantry", "▲"))

    def test_the_forms_carry_the_order_through_a_booking(self):
        html = page(sort="-kept")
        forms = re.findall(r'<form class="inline[^"]*"[^>]*>.*?</form>', html, re.S)
        self.assertTrue(forms)
        for f in forms:
            self.assertIn('<input type="hidden" name="sort" value="-kept">', f)
        self.assertNotIn('name="sort"', page())          # the default needs nothing carried


@unittest.skipUnless(ENGINE, "needs node or gjs")
class KeptColumn(unittest.TestCase):
    def test_it_shows_where_each_is_kept_and_marks_an_assumption(self):
        html = page()
        self.assertEqual({r["portion"]: r["kept"] for r in rows(html)},
                         {A: "Fridge", B: "Pantry", C: "Freezer", D: "Fridge", E: "Pantry", F: "Fridge"})
        cells = re.findall(r"<tr><td>([^<]*)</td>.*?</td><td>(Fridge|Freezer|Pantry)( <small>\(assumed\)</small>)?</td>", html, re.S)
        self.assertEqual({food: (kept, bool(assumed)) for food, kept, assumed in cells},
                         {"apples": ("Fridge", False), "Bread": ("Pantry", False), "chicken": ("Freezer", False),
                          "Milk": ("Fridge", False), "Rice": ("Pantry", True), "Zucchini": ("Fridge", False)})

    def test_a_frozen_portion_offers_the_fridge_and_others_the_freezer(self):
        html = page(sort="food")
        moves = re.findall(r'name="storage" value="(\w+)">.*?<button[^>]*>([^<]*)</button>', html)
        self.assertEqual(moves, [("Freezer", "Freeze"), ("Freezer", "Freeze"), ("Fridge", "Move to fridge"),
                                 ("Freezer", "Freeze"), ("Freezer", "Freeze"), ("Freezer", "Freeze")])


@unittest.skipUnless(ENGINE, "needs node or gjs")
class Words(unittest.TestCase):
    def test_the_page_names_no_file_and_no_model_term(self):
        html = re.sub(r"<[^>]*>", " ", re.sub(r"<script.*?</script>", "", page(), flags=re.S))     # the words shown
        for term in ("docs/", ".md", "pages/lib", "Imputed", "imputed", "perishability", "FoodKeeper", "portion"):
            self.assertNotIn(term, html, term)

    def test_an_unknown_use_by_date_says_why_in_plain_words(self):
        self.assertIn("not known <small>(no shelf life is known for it in the fridge)</small>", page())


class TheTerminalList(unittest.TestCase):
    """tools/pantry.py list --sort: the same six, in the same orders, worked out by hand above."""

    ROWS = [{"food": n.removeprefix("TEST -- "), "name": n, "days": d, "kept": k}
            for n, d, k in ((A, 16.0, "Fridge"), (B, 4.0, "Pantry"), (C, 260.0, "Freezer"), (D, 5.0, "Fridge"),
                            (E, 700.0, "Pantry"), (F, None, "Fridge"))]

    def order(self, sort):
        return [r["name"] for r in sort_rows(list(reversed(self.ROWS)), sort)]

    def test_each_order(self):
        for sort, want in (("expires", [B, D, A, C, E, F]), ("-expires", [E, C, A, D, B, F]),
                           ("food", [A, B, C, D, E, F]), ("-food", [F, E, D, C, B, A]),
                           ("kept", [D, A, F, C, B, E]), ("-kept", [B, E, C, D, A, F])):
            self.assertEqual(self.order(sort), want, sort)

    def test_an_order_it_does_not_know_is_the_default(self):
        for sort in ("price", "-", "--food", "food-"):
            self.assertEqual(self.order(sort), [B, D, A, C, E, F], sort)


if __name__ == "__main__":
    unittest.main()
