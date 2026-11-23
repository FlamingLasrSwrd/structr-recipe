"""A recipe's amounts shown as weights (mealplanner/weights.py; the owner's rule of 2026-11-23: round to a
tenth of one of the food's items, or of its usual serving, snapped to a 1, 2 or 5 step).

Worked out by hand. The tidy steps are 1, 2 and 5 times a power of ten, and x goes to the lower of two
neighbours a and b while x * x <= a * b:
  an egg, 50 g an item: a tenth is 5, a step itself;
  an onion, 150 g: 15, and 225 > 10 * 20 = 200, so 20;
  flour, a 30 g serving: 3, and 9 <= 2 * 5 = 10, so 2;
  milk, a 240 mL serving at 1.03 g/mL, 247.2 g: 24.72, and 611.1 > 200 but <= 20 * 50, so 20;
  oil, a 1 tbsp serving at 0.92 g/mL, 13.604 g: 1.36, and 1.85 <= 1 * 2, so 1.

The recipe below, "Pancakes", as weights:
  1 cup flour at 0.53 g/mL is 125.39 g: 62.7 steps of 2, so 63, 126 g (its "1 cup" beside it on the page);
  2 eggs are counted, and stay "2";
  1.5 cup milk is 365.53 g: 18.28 steps of 20, so 18, 360 g;
  0.25 tsp salt at 0.77 g/mL is 0.95 g, under 10 g by volume, so it stays "0.25 tsp";
  2 tbsp butter has no density here, so it stays; its stand-in, 0.75 of it in oil, is 1.5 tbsp, 20.41 g:
  20.41 steps of 1, so 20 g.
"""

import json
import os
import random
import subprocess
import tempfile
import unittest

from mealplanner.household import instantiate_household
from mealplanner.instructions import as_data, instructions
from mealplanner.profiles import ProfileError
from mealplanner.recipe_import import Ingredient, StepDoc, Substitute
from mealplanner.vocabulary_import import VocabularyError, import_vocabulary, parse_vocabulary
from mealplanner.weights import FoodWeights, food_weights, rounding_step, shown_amount, tidy_step
from tests.test_pantry_buy_unit import ROOT
from tests.test_signed_out import ENGINE, javascript
from tests.test_vocabulary import fdc_subset, vocabulary_data
from tests.test_vocabulary import instance as vocabulary_instance

FLOUR = FoodWeights(density=0.53, serving=30.0)
EGG = FoodWeights(each=50.0)
MILK = FoodWeights(density=1.03, serving=247.2)
SALT = FoodWeights(density=0.77, serving=0.96)
OIL = FoodWeights(density=0.92, serving=13.604)
WEIGHTS = {"Flour": FLOUR, "Egg": EGG, "Milk": MILK, "Salt": SALT, "Oil": OIL, "Butter": FoodWeights()}
PANCAKES = [StepDoc("mix the batter", "Mixing", (
    Ingredient("Flour", 1.0, "cup"), Ingredient("Egg", 2.0, "each"), Ingredient("Milk", 1.5, "cup"),
    Ingredient("Salt", 0.25, "tsp"), Ingredient("Butter", 2.0, "tbsp", substitutes=(Substitute("Oil", 0.75),))), "Batter")]


class Steps(unittest.TestCase):
    def test_tidy_steps(self):
        cases = {50 * 0.1: 5.0, 150 * 0.1: 20.0, 30 * 0.1: 2.0, 24.72: 20.0, 1.3604: 1.0, 0.5: 0.5, 1.5: 2.0,
                 1.41: 1.0, 3.2: 5.0, 7.0: 5.0, 7.1: 10.0, 0.3: 0.2, 21.5: 20.0, 1e6: 1000.0, 0.001: 0.01}
        for x, step in cases.items():
            self.assertEqual(tidy_step(x), step, x)

    def test_an_item_comes_before_a_serving_and_neither_gives_none(self):
        self.assertEqual(rounding_step(FoodWeights(each=150.0, serving=85.0)), 20.0)   # an onion's 15, not 8.5's 10
        self.assertEqual(rounding_step(FLOUR), 2.0)
        self.assertIsNone(rounding_step(FoodWeights(density=0.9)))
        self.assertIsNone(rounding_step(None))


class Shown(unittest.TestCase):
    def test_volume_and_mass_become_rounded_grams(self):
        self.assertEqual(shown_amount(1.0, "cup", FLOUR), (126.0, "g"))
        self.assertEqual(shown_amount(1.5, "cup", MILK), (360.0, "g"))
        self.assertEqual(shown_amount(1.0, "lb", EGG), (455.0, "g"))     # 453.6 g, 90.7 steps of 5
        self.assertEqual(shown_amount(1.0, "lb", None), (454.0, "g"))    # no step: to the gram

    def test_what_stays_as_written(self):
        self.assertEqual(shown_amount(2.0, "each", EGG), (2.0, "each"))            # counted
        self.assertEqual(shown_amount(0.25, "tsp", SALT), (0.25, "tsp"))          # 0.95 g, by volume
        self.assertEqual(shown_amount(2.0, "tbsp", FoodWeights()), (2.0, "tbsp"))  # no density, never a guess
        self.assertEqual(shown_amount(1.0, "cup", None), (1.0, "cup"))
        self.assertEqual(shown_amount(3.0, "handful", FLOUR), (3.0, "handful"))   # a unit not known
        self.assertEqual(shown_amount(None, "cup", FLOUR), (None, "cup"))
        self.assertEqual(shown_amount(0.9, "g", FoodWeights(each=50.0)), (0.9, "g"))   # would round to nothing

    def test_a_weight_under_10_g_stated_by_weight_is_still_weighed(self):
        self.assertEqual(shown_amount(0.25, "oz", FoodWeights(serving=0.5)), (7.1, "g"))   # 7.087 g, steps of 0.05
        self.assertEqual(shown_amount(12.0, "tsp", SALT), (45.5, "g"))   # 45.54 g, steps of 0.1 (0.096): 455


class Sentences(unittest.TestCase):
    def test_a_recipe_as_written_and_as_weights(self):
        self.assertEqual(instructions(PANCAKES), [
            "Mix 1 cup flour, 2 egg, 1.5 cup milk, 0.25 tsp salt and 2 tbsp butter (or 1.5 tbsp oil)."])
        self.assertEqual(instructions(PANCAKES, weights=WEIGHTS), [
            "Mix 126 g flour, 2 egg, 360 g milk, 0.25 tsp salt and 2 tbsp butter (or 20 g oil)."])

    def test_a_food_whose_weights_are_not_known_stays_as_written(self):
        self.assertEqual(instructions(PANCAKES, weights={}), instructions(PANCAKES))


def lib(stub: bool = True) -> str:
    """The engine code, after a stand-in `$` its top level reads (unless the caller makes its own)."""
    folder = ROOT / "pages" / "lib"
    return ("var $ = {me: null, request: {}};\n" if stub else "") + "\n".join(
        (folder / name).read_text() for name in sorted(p.name for p in folder.glob("*.js")))


def run(code: str):
    """What `code` leaves in `result`, run from a file: the twin test's program is too long for an argument."""
    program = code + '\n(typeof print === "function" ? print : console.log)(JSON.stringify(result));'
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(program)
    try:
        done = subprocess.run([ENGINE, fh.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(fh.name)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout.strip().splitlines()[-1])


@unittest.skipUnless(ENGINE, "needs node or gjs")
class Twins(unittest.TestCase):
    """The page's writer against Python's, over many random recipes, half of them as weights."""

    def test_the_javascript_writes_every_sentence_as_python_does(self):
        from tools.check_instructions import random_bearers, random_steps, random_weights
        rng = random.Random(23)
        cases = []
        for _ in range(300):
            steps, bearers, weights = random_steps(rng), random_bearers(rng), random_weights(rng)
            cases.append((steps, bearers, weights))
        payload = [{"steps": as_data(s), "bearers": {c: list(b) for c, b in br.items()},
                    "weights": None if w is None else {f: vars(x) for f, x in w.items()}} for s, br, w in cases]
        got = run(lib() + f"\nvar result = {json.dumps(payload)}.map(function (c) "
                         "{ return stepSentences(c.steps, c.bearers, c.weights); });")
        weighed = 0
        for (steps, bearers, weights), sentences in zip(cases, got):
            self.assertEqual(sentences, instructions(steps, bearers, weights))
            weighed += weights is not None and any(" g " in s for s in sentences)
        self.assertGreater(weighed, 50)       # the weights were really exercised

    def test_the_steps_match_one_by_one(self):
        xs = [0.004, 0.3, 1.41, 1.415, 3.16, 3.17, 7.07, 7.08, 15.0, 24.72, 1e5]
        self.assertEqual(javascript(lib() + f"\nvar result = {json.dumps(xs)}.map(tidyStep);"), [tidy_step(x) for x in xs])
        rows = [[1.0, "cup", vars(FLOUR)], [0.25, "tsp", vars(SALT)], [1.0, "lb", None], [2.0, "each", vars(EGG)],
                [0.9, "g", vars(EGG)], [0.25, "oz", {"density": None, "each": None, "serving": 0.5}]]
        js = javascript(lib() + f"\nvar result = {json.dumps(rows)}.map(function (r) {{ return shownAmount(r[0], r[1], r[2]); }});")
        py = [list(shown_amount(a, u, FoodWeights(**f) if f else None)) for a, u, f in rows]
        self.assertEqual(js, py)


PAGE_GRAPH = r"""
var seq = 0;
function node(type, name, props) { return Object.assign({id: "id" + (++seq), type: type, name: name, defaultSpecifications: []}, props || {}); }
var DEN = node("DomainType", "Density"), MPU = node("DomainType", "MassPerUnit"), SRV = node("DomainType", "ServingSize");
function def(on, kind, value, unit) { on.defaultSpecifications.push(node("DefaultSpecification", on.name + " " + kind.name,
                                                                         {hasKind: kind, keyedBy: [], hasValue: {value: value, unit: unit}})); }
var Food = node("DomainType", "Food", {parent: null}), Dairy = node("DomainType", "Dairy", {parent: Food});
var Flour = node("DomainType", "Flour", {parent: Food}), Egg = node("DomainType", "Egg", {parent: Food});
var Milk = node("DomainType", "Milk", {parent: Dairy}), Salt = node("DomainType", "Salt", {parent: Food});
var Butter = node("DomainType", "Butter", {parent: Food}), Oil = node("DomainType", "Oil", {parent: Food});
def(Flour, DEN, 0.53, "g_per_mL"); def(Flour, SRV, 30, "g"); def(Egg, MPU, 50, "g_per_each");
def(Milk, DEN, 1.03, "g_per_mL"); def(Dairy, SRV, 240, "ml");             // the serving inherited, by volume
def(Salt, DEN, 0.77, "g_per_mL"); def(Salt, SRV, 0.25, "tsp"); def(Oil, DEN, 0.92, "g_per_mL"); def(Oil, SRV, 1, "tbsp");
var P = "Pancakes v1";
function input(k, food, value, unit, rules) {
  return node("Specification", P + " step 1 input " + k, {hasParticipationRole: "input", specifies: food,
    hasSpecifiedQuantity: {value: value, unit: unit}, hasSubstitutionRule: rules || []});
}
var step = node("Process", P + " step 1 -- mix the batter", {instanceOf: {name: "Mixing"}, isPrecededBy: [], hasSpecification: [
  input(1, Flour, 1, "cup"), input(2, Egg, 2, "each"), input(3, Milk, 1.5, "cup"), input(4, Salt, 0.25, "tsp"),
  input(5, Butter, 2, "tbsp", [node("SubstitutionRule", P + " step 1 input 5 or 1", {candidateType: Oil, substitutionRatio: 0.75})])]});
var thePlan = node("Plan", P, {steps: [step], servingProfiles: []});
var $ = {request: REQUEST, me: ME, current: thePlan, out: "", find: function () { return []; }, print: function (s) { $.out += s; }};
"""


@unittest.skipUnless(ENGINE, "needs node or gjs")
class RecipePage(unittest.TestCase):
    """pages/recipe.js over a stand-in graph: the address, else the person's preference."""

    def page(self, request: dict, me) -> tuple[dict, str]:
        graph = PAGE_GRAPH.replace("REQUEST", json.dumps(request)).replace("ME", json.dumps(me))
        code = lib(stub=False) + "\n" + (ROOT / "pages" / "common.js").read_text() + "\n" + (ROOT / "pages" / "recipe.js").read_text()
        html = javascript("var result = (function () {\n" + graph + "\n" + code + "\nreturn $.out; })();")
        data = json.loads(html.split('id="page-data">', 1)[1].split("</script>", 1)[0])
        return data, html

    def test_a_person_who_prefers_weights_sees_them(self):
        data, html = self.page({}, {"name": "Jamie", "preferredMeasure": "weight"})
        self.assertEqual(data["measure"], "weight")
        self.assertEqual(data["instructions"], ["Mix 126 g flour, 2 egg, 360 g milk, 0.25 tsp salt and 2 tbsp butter (or 20 g oil)."])
        self.assertEqual([(i["amount"], i["unit"], i["written"]) for i in data["ingredients"]],
                         [(126, "g", [1, "cup"]), (2, "each", None), (360, "g", [1.5, "cup"]), (0.25, "tsp", None), (2, "tbsp", None)])
        self.assertIn("<li>126 g Flour <small>(1 cup)</small></li>", html)
        self.assertIn("?measure=written", html)

    def test_as_written_unless_asked(self):
        for request, me in (({}, {"name": "Jamie"}), ({}, None), ({"measure": "written"}, {"name": "Jamie", "preferredMeasure": "weight"})):
            data, html = self.page(request, me)
            self.assertEqual(data["measure"], "written", (request, me))
            self.assertEqual(data["instructions"], ["Mix 1 cup flour, 2 egg, 1.5 cup milk, 0.25 tsp salt and 2 tbsp butter (or 1.5 tbsp oil)."])
            self.assertIn("<li>1 cup Flour</li>", html)
        data, _ = self.page({"measure": "weight"}, {"name": "Jamie"})
        self.assertEqual(data["measure"], "weight")


class Vocabulary(unittest.TestCase):
    def test_a_serving_is_read_with_its_source(self):
        data = vocabulary_data()
        data["food"][0]["serving"] = {"amount": 85, "unit": "g", "source": "FDA reference amount: vegetables"}
        data["food"][5]["serving"] = {"amount": 0.25, "unit": "tsp", "source": "FDA reference amount: salt", "status": "sourced"}
        foods = {f.name: f for f in parse_vocabulary(data, fdc_subset()).foods}
        self.assertEqual((foods["Alliums"].serving.amount, foods["Alliums"].serving.unit, foods["Alliums"].serving.status),
                         (85.0, "g", "estimated"))
        self.assertEqual(foods["Kosher salt"].serving.status, "sourced")
        self.assertIsNone(foods["Garlic"].serving)

    def test_a_bad_serving_is_refused(self):
        cases = [({"amount": 1, "unit": "each", "source": "x"}, "by weight or volume"),
                 ({"amount": 0, "unit": "g", "source": "x"}, "above zero"),
                 ({"amount": 30, "unit": "g"}, "needs its source"),
                 ({"amount": 30, "unit": "g", "source": "x", "per": "cup"}, "serving is"),
                 ({"amount": 30, "unit": "g", "source": "x", "status": "guessed"}, "status"),
                 (30, "serving is")]
        for serving, fragment in cases:
            data = vocabulary_data()
            data["food"][0]["serving"] = serving
            with self.assertRaises(VocabularyError) as caught:
                parse_vocabulary(data, fdc_subset())
            self.assertTrue(any(fragment in p for p in caught.exception.problems), (serving, caught.exception.problems))

    def test_servings_are_loaded_and_resolved_along_the_hierarchy(self):
        """Alliums' 85 g serving reaches Onion, below it; Kosher salt's 0.25 tsp is 0.25 * 4.92892 mL at its
        density, 3.8 g per tsp: 0.95 g. Garlic's clove is its item, so its step is a tenth of that."""
        data = vocabulary_data()
        data["food"][0]["serving"] = {"amount": 85, "unit": "g", "source": "FDA reference amount: vegetables"}
        data["food"][5]["serving"] = {"amount": 0.25, "unit": "tsp", "source": "FDA reference amount: salt"}
        g = vocabulary_instance()
        imported = import_vocabulary(g, parse_vocabulary(data, fdc_subset()))
        ids = {r["name"]: r["id"] for r in g.get_all("DomainType")["result"]}
        spec = next(r for r in g.get_all("DefaultSpecification")["result"] if r["name"] == "Alliums serving")
        self.assertEqual((spec["hasKind"]["name"], spec["provenance"], spec["source"]),
                         ("ServingSize", "estimated", "FDA reference amount: vegetables"))
        onion, salt = food_weights(g, ids["Onion"]), food_weights(g, ids["Kosher salt"])
        self.assertEqual(onion.serving, 85.0)
        self.assertAlmostEqual(salt.serving, 0.95, places=6)
        self.assertAlmostEqual(salt.density, 3.8 / 4.92892, places=6)
        self.assertIsNone(onion.each)
        again = import_vocabulary(g, parse_vocabulary(data, fdc_subset()))
        self.assertEqual(again.counts["created"], 0)                   # idempotent
        data["food"][0]["serving"]["amount"] = 100
        changed = import_vocabulary(g, parse_vocabulary(data, fdc_subset()))
        self.assertEqual((changed.counts["changed"], changed.affected), (1, set()))   # no nutrition rests on it
        self.assertEqual(food_weights(g, ids["Onion"]).serving, 100.0)

    def test_the_curated_vocabulary_gives_every_food_a_step(self):
        """Every food in data/vocabulary.toml but the label-counted supplements has an item or a serving,
        on itself or above it, so no weight falls back to the gram."""
        from mealplanner.vocabulary_import import read_vocabulary
        foods = {f.name: f for f in read_vocabulary(str(ROOT / "data" / "vocabulary.toml")).foods}

        def stepped(name):
            while name in foods:
                if foods[name].each or foods[name].serving or foods[name].label:
                    return True
                name = foods[name].parent
            return False
        self.assertEqual([n for n in foods if not stepped(n) and n != "Dietary supplement"], [])

    def test_each_cited_reference_amount_is_a_row_of_the_pinned_table(self):
        """A serving that cites Table 2 of 21 CFR 101.12, 9 CFR 317.312 or 9 CFR 381.412 quotes a row of
        data/racc/table2.tsv (the start of its category, or its start and a later part around " ... "),
        and a `sourced` one states an amount that row gives, read from the TSV and the TOML directly."""
        import re
        import tomllib
        with open(ROOT / "data" / "racc" / "table2.tsv", encoding="utf-8") as f:
            header, *lines = f.read().splitlines()
        rows = [dict(zip(header.split("\t"), line.split("\t"))) for line in lines]
        with open(ROOT / "data" / "vocabulary.toml", "rb") as f:
            foods = tomllib.load(f)["food"]
        problems, cited = [], 0
        for food in foods:
            serving = food.get("serving")
            m = re.match(r'(\d+ CFR [\d.]+ Table 2): "([^"]+)"', serving["source"]) if serving else None
            if not m:
                continue
            cited += 1
            table, quote = m.groups()
            first, *rest = quote.split(" ... ")
            matches = [r for r in rows if r["table"] == table and r["category"].startswith(first)
                       and all(part in r["category"] for part in rest)]
            exact = [r for r in matches if r["category"] == quote]
            matches = exact or matches
            if not matches:
                problems.append(f"{food['name']}: no row of {table} reads {quote!r}")
                continue
            if serving.get("status") != "sourced":
                continue
            amount = {0.25: "1/4", 0.5: "0.5", 0.6: "0.6"}.get(serving["amount"], str(serving["amount"]))
            unit = {"ml": "mL"}.get(serving["unit"], serving["unit"])
            stated = re.compile(rf"(?<![\d/.]){re.escape(amount)} ?{re.escape(unit)}\b")
            amounts = [r["reference_amount"] + " " + (r["label_statement_or_ready_to_cook"] if r["table"].startswith("9 CFR") else "")
                       for r in matches]
            if not any(stated.search(a) for a in amounts):
                problems.append(f"{food['name']}: {amount} {unit} is not what {quote!r} gives: {amounts}")
        self.assertEqual(problems, [])
        self.assertGreater(cited, 150)                     # the check reached the servings at all


class Household(unittest.TestCase):
    def setUp(self):
        from tests.test_household import Household as H
        self.h = H()
        self.h.setUp()

    def schema(self, g):
        g.add("SchemaNode", "Person", "Person")
        g.add("SchemaProperty", "preferredMeasure", "preferredMeasure", schemaNode="Person")

    def test_a_persons_measure_is_written_to_them(self):
        g = self.h.g()
        self.schema(g)
        people = self.h.selection()["person"]
        people[0]["measure"] = "weight"
        instantiate_household(g, self.h.selection(person=people), self.h.root)
        rows = {r["name"]: r for r in g.get_all("Person")["result"]}
        self.assertEqual((rows["Jamie"].get("preferredMeasure"), rows["Alex"].get("preferredMeasure")), ("weight", None))

    def test_a_measure_needs_the_schema_and_a_known_value(self):
        people = self.h.selection()["person"]
        people[0]["measure"] = "weight"
        with self.assertRaises(ProfileError) as caught:
            instantiate_household(self.h.g(), self.h.selection(person=people), self.h.root)
        self.assertIn("scripts/49a", str(caught.exception.problems))
        people[0]["measure"] = "volume"
        g = self.h.g()
        self.schema(g)
        with self.assertRaises(ProfileError) as caught:
            instantiate_household(g, self.h.selection(person=people), self.h.root)
        self.assertIn("measure is one of", str(caught.exception.problems))


if __name__ == "__main__":
    unittest.main()
