"""The pages' side of a food bought instead (pages/lib/92_substitutes.js), against mealplanner/substitutes.py and
mealplanner/alternatives.py, over tests/test_substitutes.py's kitchen: the engine code runs in node or gjs, where
either is installed, over the same in-memory graph, each relationship resolved to the node it names as Structr's
scripting gives it. On an instance tools/check_pages.py compares the pages with Python the same way.
"""

import json
import unittest

from mealplanner.alternatives import alternatives
from mealplanner.nutrition_scope import entry_nutrient_figure
from mealplanner.shopping import shopping_list
from mealplanner.substitutes import use_instead
from tests.fakegraph import Ref
from tests.planning_graph import add_portion
from tests.test_pantry_buy_unit import ROOT
from tests.test_signed_out import ENGINE, javascript
from tests.test_substitutes import NOW, PROTEIN, kitchen, priced, rule

PRICES = {"Noodles": 0.5, "Spaghetti": 0.4, "Rice Noodles": 1.0}


def as_js(g) -> str:
    """The graph as JavaScript: N (nodes by id, each Ref the node itself) and a $ that finds them."""
    def plain(value):
        if isinstance(value, Ref):
            return {"$ref": value.id}
        if isinstance(value, list):
            return [plain(v) for v in value]
        return value
    nodes = {nid: {k: plain(v) for k, v in node.items()} for nid, node in g.nodes.items()}
    return ("var N = " + json.dumps(nodes) + ";\n"
            "Object.keys(N).forEach(function (id) { var n = N[id]; Object.keys(n).forEach(function (k) {\n"
            "  var v = n[k];\n"
            "  if (v && v.$ref) n[k] = N[v.$ref] || null;\n"
            "  else if (Array.isArray(v)) n[k] = v.map(function (x) { return x && x.$ref ? N[x.$ref] : x; });\n"
            "}); });\n"
            "var $ = {me: null, request: {}, find: function (type, f) {\n"
            "  return Object.keys(N).map(function (id) { return N[id]; }).filter(function (n) {\n"
            "    return n.type === type && (!f || Object.keys(f).every(function (k) { return n[k] === f[k]; })); }); }};\n")


def run(g, body: str):
    lib = ROOT / "pages" / "lib"
    engine = "\n".join((lib / name).read_text() for name in sorted(p.name for p in lib.glob("*.js")))
    return javascript("var result = (function () {\n" + as_js(g) + engine + "\n" + body + "\n})();")


@unittest.skipUnless(ENGINE, "no node or gjs")
class ThePagesAgree(unittest.TestCase):
    def test_the_alternatives(self):
        g = kitchen()
        rule(g, "in0 pasta or 2 Udon", "in0 pasta", "Udon", 1.0, excluded=True)
        rule(g, "in0 pasta or 3 Spaghetti", "in0 pasta", "Spaghetti", 1.0)
        add_portion(g, "rice noodles on hand", "Rice Noodles", 120.0)          # so it comes first, though listed first too
        table = {food: {"hasValue": {"value": v}} for food, v in PRICES.items()}
        shown = run(g, f"var a = alternativesFor(N.week, N.Noodles, {json.dumps(table)}, {json.dumps(PROTEIN)}); return a;")
        want = alternatives(g, "week", "Noodles", NOW, priced(**PRICES), PROTEIN)
        self.assertEqual((shown["food"], shown["grams"], [tuple(m) for m in shown["meals"]]), (want.food, want.grams, want.meals))
        got = [(o["kind"], o["food"], o["meals"], o["grams"], o["have"], o["ratio"], o["kinds"], o["checked"]) for o in shown["options"]]
        self.assertEqual(got, [(o.kind, o.food, o.meals, o.grams, o.have, o.ratio, o.kinds, o.checked) for o in want.options])
        for row, option in zip(shown["options"], want.options):
            if option.effect is None:
                self.assertIsNone(row["effect"])
                continue
            self.assertAlmostEqual(row["effect"]["cost"], option.effect.cost)
            self.assertEqual([tuple(n[:2]) for n in row["effect"]["nutrients"]], [n[:2] for n in option.effect.nutrients])
            for a, b in zip(row["effect"]["nutrients"], option.effect.nutrients):
                self.assertAlmostEqual(a[2], b[2])

    def test_nutrients_are_listed_in_pythons_order(self):
        # by character code, as sorted() in mealplanner/alternatives.py: capitals before small letters, so
        # "PUFA 18:2" before "Phosphorus" ('U' < 'h') and "iron" last; worked out by hand (seen on 2026-11-25,
        # when the page sorted with localeCompare and tools/check_pages.py found 21 lines in another order)
        nutrients = {"n1": ["Phosphorus", "mg"], "n2": ["iron", "mg"], "n3": ["Protein", "g"], "n4": ["PUFA 18:2", "g"]}
        shown = run(kitchen(), f"return nutrientIdsByName({json.dumps(nutrients)});")
        self.assertEqual(shown, ["n4", "n1", "n3", "n2"])

    def test_the_shopping_list_and_a_meals_nutrition_follow_a_swap(self):
        g = kitchen()
        # the omelette's 6 eggs, and the recipe's 3 duck eggs for them: duck eggs have no weight per item, so by weight
        g.add("QuantitySpecification", "each Eggs value", value=50.0, unit="g_per_each")
        g.add("DefaultSpecification", "each Eggs", hasKind=Ref("MassPerUnit"), keyedBy=[], hasValue=Ref("each Eggs value"))
        g.nodes["Eggs"]["defaultSpecifications"].append(Ref("each Eggs"))
        g.nodes["q in0 omelette"].update(value=6, unit="each")
        rule(g, "in0 omelette or 1 Duck Eggs", "in0 omelette", "Duck Eggs", 0.5)
        use_instead(g, "week", "Noodles", "Spaghetti")
        use_instead(g, "week", "Eggs", "Duck Eggs", entry_ids=["e1"])
        shown = run(g, "var n = needs(N.week); var out = {}; Object.keys(n.pools).forEach(function (id) {"
                       " var p = n.pools[id]; out[p.food.name] = [p.need, p.instead]; });"
                       " return {pools: out, protein: ['e1', 'e2', 'e3'].map(function (e) { return intakeFigure(N[e], 'Protein', 'g'); })};")
        want = shopping_list(g, "week", NOW)
        self.assertEqual({food: (need, sorted(instead)) for food, (need, instead) in shown["pools"].items()},
                         {line.food: (line.need, line.instead) for line in want.to_buy + want.covered})
        # the page reads only a recipe's stored figures (J28): stored here as Python works them out
        for e, row in zip(("e1", "e2", "e3"), shown["protein"]):
            self.assertIsNone(row["amount"])          # nothing stored, so nothing shown: as for a meal with no swap
        for plan, per_serving in (("omelette", 24.0), ("pasta", 12.0)):
            g.add("NutrientProfile", f"stored {plan}", forNutrient=Ref("Protein"), basis="per_serving", unit="g",
                  amount=per_serving, provenance="calculated")
            g.nodes[plan]["servingProfiles"] = [Ref(f"stored {plan}")]
        shown = run(g, "return ['e1', 'e2', 'e3'].map(function (e) { return intakeFigure(N[e], 'Protein', 'g'); });")
        for e, row in zip(("e1", "e2", "e3"), shown):
            amount, _, estimated = entry_nutrient_figure(g, g.get_all("MealPlanEntry", e)["result"], "Protein")
            self.assertAlmostEqual(row["amount"], amount, msg=e)
            self.assertEqual(row["estimated"], estimated, e)


if __name__ == "__main__":
    unittest.main()
