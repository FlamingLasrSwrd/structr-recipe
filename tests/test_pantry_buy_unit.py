"""The pantry page's Buy picks a food's unit once it is chosen (pages/pantry.js, the owner's request of
2026-11-22), as products.buy_unit does (tests/test_packages.py and tests/test_products.py test that; on
an instance tools/check_pages.py compares the two). The whole page runs in node or gjs, where either is
installed, over a stand-in graph, and then its script against a stand-in form.

Worked out by hand. The package level "US supermarket" sells Flour in a 5 lb and a 2 lb bag, Milk by
the gallon (128 fl_oz; it has a density), Egg by the dozen (12 each; it has a weight per item), Butter
in 1 lb and Honey in 12 fl_oz. So Flour is lb, Milk fl_oz, Egg each, and Butter (salted), below Butter,
takes its lb. Honey has no density, so its fluid ounces do not convert and it is grams, as Salt, sold
in nothing, is: grams are the form's own default and left out of the page's table. Butter is a group
(Butter (salted) sits under it) and is not offered at all. The products Farm eggs dozen (12 each) and
Dairy milk 1 L (1 l) take their own: each, and l rather than Milk's fl_oz.
"""

import json
import pathlib
import re
import unittest

from tests.test_signed_out import ENGINE, javascript

ROOT = pathlib.Path(__file__).resolve().parent.parent

GRAPH = r"""
var N = {}, seq = 0;
function node(type, name, props) {
  var n = Object.assign({id: "id" + (++seq), type: type, name: name, defaultSpecifications: [], children: []}, props || {});
  (N[type] = N[type] || []).push(n); return n;
}
var $ = {request: {}, me: {name: "Jamie"}, current: null, out: "",
  find: function (type, f) { return (N[type] || []).filter(function (n) { return !f || Object.keys(f).every(function (k) { return n[k] === f[k]; }); }); },
  print: function (s) { $.out += s; }};
var food = node("TypeHierarchy", "Food Identity", {domainTypes: []});
var PQ = node("DomainType", "PurchaseQuantity"), DEN = node("DomainType", "Density"), MPU = node("DomainType", "MassPerUnit");
function def(on, kind, value, unit, keys, name) {
  on.defaultSpecifications.push(node("DefaultSpecification", name || on.name + " " + kind.name,
                                     {hasKind: kind, keyedBy: keys || [], hasValue: {value: value, unit: unit}}));
}
function f(name, parent) {
  var t = node("DomainType", name, {hierarchy: food, parent: parent || null});
  food.domainTypes.push(t); if (parent) parent.children.push(t); return t;
}
var Flour = f("Flour"), Milk = f("Milk"), Egg = f("Egg"), Butter = f("Butter"), Salted = f("Butter (salted)", Butter);
var Salt = f("Salt"), Honey = f("Honey");
def(Milk, DEN, 1.03, "g_per_mL"); def(Egg, MPU, 50, "g_per_each");
var dozen = f("Farm eggs dozen", Egg), carton = f("Dairy milk 1 L", Milk);
def(dozen, PQ, 12, "each"); def(carton, PQ, 1, "l");
node("Concept", "GTIN", {identifiersInScheme: [{denotesType: dozen}, {denotesType: carton}]});
var US = node("DomainType", "US supermarket");
[[Flour, 5, "lb", "5 lb bag"], [Flour, 2, "lb", "2 lb bag"], [Milk, 128, "fl_oz", "gallon"], [Egg, 12, "each", "dozen"],
 [Butter, 1, "lb", "1 lb"], [Honey, 12, "fl_oz", "12 fl oz"]].forEach(function (s) {
  def(US, PQ, s[1], s[2], [s[0]], "US supermarket -- " + s[0].name + " -- " + s[3]);
});
"""


def page_code() -> str:
    lib = ROOT / "pages" / "lib"
    engine = "\n".join((lib / name).read_text() for name in sorted(p.name for p in lib.glob("*.js")))
    return engine + "\n" + (ROOT / "pages" / "common.js").read_text() + "\n" + (ROOT / "pages" / "pantry.js").read_text()


def printed() -> str:
    return javascript("var result = (function () {\n" + GRAPH + "\n" + page_code() + "\nreturn $.out; })();")


def picks(html: str, typed: list[str]) -> list[str]:
    """The unit the form shows after each name is typed into Buy's food field, in turn."""
    data = {name: json.loads(re.search(f'id="{name}">(.*?)</script>', html, re.S).group(1)) for name in ("buy-data", "buy-units")}
    script = [s for s in re.findall(r"<script>(.*?)</script>", html, re.S) if "buy-units" in s]
    assert len(script) == 1, script
    return javascript(f"""
var handlers = [], unit = {{value: "g"}};
var food = {{value: "", form: {{querySelector: function (q) {{ return q === "select[name=unit]" ? unit : null; }}}},
            addEventListener: function (e, h) {{ if (e === "input") handlers.push(h); }}}};
var data = {json.dumps(data)};
var document = {{querySelector: function (q) {{ return q === "details.buy input[name=food]" ? food : null; }},
                getElementById: function (id) {{ return {{textContent: JSON.stringify(data[id])}}; }}}};
{script[0]}
var result = {json.dumps(typed)}.map(function (v) {{ food.value = v; handlers.forEach(function (h) {{ h(); }}); return unit.value; }});""")


@unittest.skipUnless(ENGINE, "no node or gjs")
class BuyPicksTheUnit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = printed()

    def test_the_page_picks_the_unit_of_a_products_or_foods_package(self):
        units = json.loads(re.search(r'id="buy-units">(.*?)</script>', self.html, re.S).group(1))
        self.assertEqual(units, {"Flour": "lb", "Milk": "fl_oz", "Egg": "each", "Butter (salted)": "lb",
                                 "Farm eggs dozen": "each", "Dairy milk 1 L": "l"})

    def test_choosing_a_food_sets_the_unit_and_part_of_a_name_does_not(self):
        typed = ["Milk", "Mi", "Salt", "Dairy milk 1 L", "Flour", "Honey", "Butter (salted)", " Egg ", "Nonsense", "Butter"]
        self.assertEqual(picks(self.html, typed), ["fl_oz", "fl_oz", "g", "l", "lb", "g", "lb", "each", "each", "each"])


if __name__ == "__main__":
    unittest.main()
