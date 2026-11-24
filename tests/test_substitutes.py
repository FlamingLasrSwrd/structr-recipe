"""A food bought in place of what the shopping list says (mealplanner/substitutes.py), and the alternatives
the shopping page offers (mealplanner/alternatives.py).

Worked by hand on tests/test_pantry.py's kitchen: an omelette (yield 2) takes 300 g of eggs; pasta (yield 2)
takes 200 g of noodles and 100 g of eggs. Monday the 28th's omelette is cooked for 4 servings (600 g of
eggs), Tuesday the 29th's pasta for 2 (200 g of noodles, 100 g of eggs), and Wednesday eats the omelette's
leftovers. 250 g of eggs are on hand. Noodles sit under Pasta, beside Spaghetti, Rice Noodles and Udon;
the pasta recipe says 0.8 g of rice noodles may stand in for a gram of noodles (its unit is grams).
Protein per 100 g: noodles 10, spaghetti 13, rice noodles 6, eggs 12, duck eggs 15; udon has no figures.
Prices per 100 g: noodles $0.50, spaghetti $0.40, rice noodles $1.00.
"""

import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from mealplanner.alternatives import alternatives, describe
from mealplanner.nutrition_scope import entry_nutrient_figure
from mealplanner.pantry import buy, cook
from mealplanner.recipe_import import _rules
from mealplanner.shopping import describe as describe_list, shopping_list
from mealplanner.substitutes import SwapError, entry_swaps, stop_using, use_instead
from tests.fakegraph import Ref, at, when
from tests.planning_graph import add_entry, add_portion, add_type
from tests.test_pantry import Graph, pantry

NOW = when(25, 12)
PROTEIN = {"Protein": ("Protein", "g")}


class SwapGraph(Graph):
    RELATIONS = Graph.RELATIONS | {"forSpecification", "candidateType", "usesSubstitution", "viaSubstitution"}
    REVERSES = {**Graph.REVERSES, "forSpecification": "hasSubstitutionRule", "candidateType": "candidateOfRules",
                "viaSubstitution": "allocationsVia"}

    def _store(self, node_id, fields):
        if "usesSubstitution" in fields:          # a list both ways: the rule's usedByEntries
            for ref in self.nodes[node_id].get("usesSubstitution") or []:
                rule = self.nodes[ref.id]
                rule["usedByEntries"] = [r for r in rule.get("usedByEntries") or [] if r.id != node_id]
            for rule_id in fields["usesSubstitution"] or []:
                self.nodes[rule_id].setdefault("usedByEntries", []).append(Ref(node_id))
        super()._store(node_id, fields)


def protein(g, food, amount):
    g.add("NutrientProfile", f"protein {food}", forNutrient=Ref("Protein"), basis="per_100g", unit="g", amount=amount,
          provenance="sourced")
    g.nodes[food]["nutrientProfilesAbout"].append(Ref(f"protein {food}"))


def kitchen():
    base = pantry()
    g = SwapGraph()
    g.nodes = base.nodes
    add_type(g, "Pasta")
    g.nodes["Noodles"]["parent"] = Ref("Pasta")
    g.nodes["Pasta"]["children"].append(Ref("Noodles"))
    for name in ("Spaghetti", "Rice Noodles", "Udon"):
        add_type(g, name, "Pasta")
    add_type(g, "Duck Eggs")
    for food, amount in (("Noodles", 10), ("Spaghetti", 13), ("Rice Noodles", 6), ("Eggs", 12), ("Duck Eggs", 15)):
        protein(g, food, amount)
    for spec in ("in0 omelette", "in0 pasta", "in1 pasta"):
        g.nodes[spec]["hasSubstitutionRule"] = []
    rule(g, "in0 pasta or 1 Rice Noodles", "in0 pasta", "Rice Noodles", 0.8)
    for name, plan, day, servings in (("e1", "omelette", 28, 4.0), ("e2", "pasta", 29, 2.0)):
        add_entry(g, name, plan, at(day, 18), servings=servings)
    add_entry(g, "e3", None, at(30, 18), leftover_of="e1")
    add_portion(g, "eggs on hand", "Eggs", 250.0)
    return g


def rule(g, name, spec, food, ratio, excluded=False):
    g.add("SubstitutionRule", name, forSpecification=Ref(spec), candidateType=Ref(food), substitutionRatio=ratio,
          isExcluded=excluded, usedByEntries=[])
    g.nodes[spec]["hasSubstitutionRule"].append(Ref(name))


def lines(g):
    shopping = shopping_list(g, "week", NOW)
    return {line.food: (line.buy, line.instead) for line in shopping.to_buy}


def priced(**per_100g):
    return {food: SimpleNamespace(quantity={"value": value}, spec={"provenance": "sourced"}) for food, value in per_100g.items()}


class BoughtInstead(unittest.TestCase):
    def test_a_food_with_no_rule_stands_in_one_to_one_by_weight_for_that_weeks_meals(self):
        g = kitchen()
        self.assertEqual(lines(g), {"Eggs": (450.0, []), "Noodles": (200.0, [])})
        done = use_instead(g, "week", "Noodles", "Spaghetti")
        self.assertEqual(done.meals, ["e2"])
        self.assertEqual(done.created, ["in0 pasta or Spaghetti (bought instead)"])
        made = g.nodes["SubstitutionRule:in0 pasta or Spaghetti (bought instead)"]
        self.assertEqual((made["isOneOff"], made["substitutionRatio"], made["candidateType"].id), (True, 1.0, "Spaghetti"))
        self.assertEqual(lines(g), {"Eggs": (450.0, []), "Spaghetti": (200.0, ["Noodles"])})
        self.assertEqual(g.nodes["in0 pasta"]["specifies"].id, "Noodles")         # the recipe is left as it is

    def test_a_food_bought_instead_that_the_pantry_covers_says_what_it_is_in_place_of(self):
        g = kitchen()
        use_instead(g, "week", "Noodles", "Spaghetti")
        add_portion(g, "spaghetti on hand", "Spaghetti", 300.0)
        shopping = shopping_list(g, "week", NOW)
        self.assertEqual([(line.food, line.need, line.instead) for line in shopping.covered], [("Spaghetti", 200.0, ["Noodles"])])
        self.assertIn("Spaghetti (200 of 300 g, in place of Noodles)", describe_list(shopping, ZoneInfo("America/Edmonton")))

    def test_the_recipes_own_rule_is_used_with_its_ratio(self):
        g = kitchen()
        done = use_instead(g, "week", "Noodles", "Rice Noodles")
        self.assertEqual(done.created, [])
        self.assertEqual([r.id for r in g.nodes["e2"]["usesSubstitution"]], ["in0 pasta or 1 Rice Noodles"])
        self.assertEqual(lines(g)["Rice Noodles"], (160.0, ["Noodles"]))                 # 200 g x 0.8

    def test_a_recipes_rule_is_in_the_recipes_unit(self):
        g = kitchen()
        for food, grams in (("Eggs", 50.0), ("Duck Eggs", 70.0)):
            g.add("QuantitySpecification", f"each {food} value", value=grams, unit="g_per_each")
            g.add("DefaultSpecification", f"each {food}", hasKind=Ref("MassPerUnit"), keyedBy=[], hasValue=Ref(f"each {food} value"))
            g.nodes[food]["defaultSpecifications"].append(Ref(f"each {food}"))
        g.nodes["q in0 omelette"].update(value=6, unit="each")                     # 6 eggs, 300 g
        rule(g, "in0 omelette or 1 Duck Eggs", "in0 omelette", "Duck Eggs", 0.5)   # 3 duck eggs for 6
        use_instead(g, "week", "Eggs", "Duck Eggs", entry_ids=["e1"])
        self.assertAlmostEqual(lines(g)["Duck Eggs"][0], 3 * 70.0 * 2)               # 4 servings of a yield of 2

    def test_a_rule_that_rules_the_food_out_is_kept_to(self):
        g = kitchen()
        rule(g, "in0 pasta or 2 Spaghetti", "in0 pasta", "Spaghetti", 1.0, excluded=True)
        done = use_instead(g, "week", "Noodles", "Spaghetti")
        self.assertEqual(done.meals, [])
        self.assertIn("must not stand in", done.notes[0])
        self.assertEqual(lines(g)["Noodles"], (200.0, []))

    def test_booking_it_twice_writes_nothing_new(self):
        g = kitchen()
        use_instead(g, "week", "Noodles", "Spaghetti")
        posts, uses = g.posts, list(g.nodes["e2"]["usesSubstitution"])
        again = use_instead(g, "week", "Noodles", "Spaghetti")
        self.assertEqual((again.created, again.meals, g.posts), ([], [], posts))
        self.assertEqual([r.id for r in g.nodes["e2"]["usesSubstitution"]], [r.id for r in uses])

    def test_only_the_meals_asked_for(self):
        g = kitchen()
        use_instead(g, "week", "Eggs", "Duck Eggs", entry_ids=["e2"])
        self.assertEqual(lines(g), {"Eggs": (350.0, []), "Duck Eggs": (100.0, ["Eggs"]), "Noodles": (200.0, [])})

    def test_a_kind_of_the_food_needs_no_swap(self):
        g = kitchen()
        add_type(g, "Egg Noodles", "Noodles")
        with self.assertRaises(SwapError):
            use_instead(g, "week", "Noodles", "Egg Noodles")

    def test_a_cooked_meal_or_a_skipped_one_is_left_as_it_is(self):
        g = kitchen()
        g.nodes["e2"]["isSkipped"] = True
        self.assertEqual(use_instead(g, "week", "Noodles", "Spaghetti").meals, [])

    def test_undone_the_meal_uses_the_recipes_food_again_and_an_unused_one_off_rule_goes(self):
        g = kitchen()
        use_instead(g, "week", "Noodles", "Spaghetti")
        made = "SubstitutionRule:in0 pasta or Spaghetti (bought instead)"
        self.assertEqual(stop_using(g, "e2", made), ["in0 pasta or Spaghetti (bought instead)"])
        self.assertNotIn(made, g.nodes)
        self.assertEqual(lines(g)["Noodles"], (200.0, []))
        use_instead(g, "week", "Noodles", "Rice Noodles")
        self.assertEqual(stop_using(g, "e2", "in0 pasta or 1 Rice Noodles"), [])          # the recipe's own stays
        self.assertIn("in0 pasta or 1 Rice Noodles", g.nodes)

    def test_a_one_off_rule_is_not_the_recipes(self):
        g = kitchen()
        use_instead(g, "week", "Noodles", "Spaghetti")
        spec = g.get_all("Specification", "in0 pasta")["result"]
        self.assertEqual([s.food for s in _rules(g, spec)], ["Rice Noodles"])


class Cooked(unittest.TestCase):
    def test_the_cook_draws_the_food_bought_and_says_which_rule_it_followed(self):
        g = kitchen()
        buy(g, "Noodles", 50, "g", NOW, "t0")                   # some of the recipe's food on hand: not drawn
        buy(g, "Spaghetti", 250, "g", NOW, "t1")
        use_instead(g, "week", "Noodles", "Spaghetti")
        booking, short = cook(g, "e2", when(29, 17), "c1")
        draws = {n["name"]: n for n in g.nodes.values() if n["type"] == "Allocation"}
        spaghetti = draws["Cook c1 -- pasta -- Spaghetti from Purchase t1 -- Spaghetti"]
        self.assertEqual(g.nodes[spaghetti["hasActualQuantity"].id]["value"], 200.0)
        self.assertEqual(spaghetti["viaSubstitution"].id, "SubstitutionRule:in0 pasta or Spaghetti (bought instead)")
        self.assertEqual(spaghetti["fulfills"].id, "in0 pasta")
        self.assertFalse([d for d in draws if "Noodles" in d])
        self.assertEqual(short, [])                       # the eggs from the 250 g on hand


class Eaten(unittest.TestCase):
    def test_a_meals_nutrition_counts_the_food_eaten(self):
        g = kitchen()
        before = entry_nutrient_figure(g, g.get_all("MealPlanEntry", "e2")["result"], "Protein")
        use_instead(g, "week", "Noodles", "Spaghetti")
        after = entry_nutrient_figure(g, g.get_all("MealPlanEntry", "e2")["result"], "Protein")
        # 200 g at 13 g in place of 10 g per 100 g, over the recipe's 2 servings: 3 g a serving, one eaten
        self.assertAlmostEqual(after[0] - before[0], 3.0)
        self.assertEqual((before[2], after[2]), (False, True))       # one to one by weight is an estimate

    def test_leftovers_eat_what_their_cook_used(self):
        g = kitchen()
        before = entry_nutrient_figure(g, g.get_all("MealPlanEntry", "e3")["result"], "Protein")[0]
        use_instead(g, "week", "Eggs", "Duck Eggs")
        after = entry_nutrient_figure(g, g.get_all("MealPlanEntry", "e3")["result"], "Protein")[0]
        self.assertAlmostEqual(after - before, 300 * 3 / 100 / 2)             # 4.5 g a serving

    def test_a_food_with_no_figure_makes_the_meal_unknown(self):
        g = kitchen()
        use_instead(g, "week", "Noodles", "Udon")
        self.assertIsNone(entry_nutrient_figure(g, g.get_all("MealPlanEntry", "e2")["result"], "Protein")[0])

    def test_a_meal_with_no_swap_reads_as_before(self):
        g = kitchen()
        self.assertEqual(entry_swaps(g, g.get_all("MealPlanEntry", "e2")["result"]), {})


class Suggested(unittest.TestCase):
    def test_best_first_with_what_each_does_to_cost_and_protein(self):
        g = kitchen()
        alts = alternatives(g, "week", "Noodles", NOW, priced(Noodles=0.5, Spaghetti=0.4, **{"Rice Noodles": 1.0}), PROTEIN)
        self.assertEqual((alts.grams, alts.meals), (200.0, [("e2", "pasta")]))
        got = [(a.kind, a.food, a.meals, round(a.grams, 6), a.ratio, a.checked) for a in alts.options]
        self.assertEqual(got, [("same", None, ["e2"], 200.0, None, True),
                               ("recipe", "Rice Noodles", ["e2"], 160.0, 0.8, True),
                               ("similar", "Spaghetti", ["e2"], 200.0, 1.0, False),
                               ("similar", "Udon", ["e2"], 200.0, 1.0, False),
                               ("replan", None, ["e2"], 0.0, None, True)])
        rice, spaghetti, udon = alts.options[1:4]
        self.assertAlmostEqual(rice.effect.cost, (160 * 1.0 - 200 * 0.5) / 100)              # +$0.60
        self.assertAlmostEqual(rice.effect.nutrients[0][2], 160 * 6 / 100 - 200 * 10 / 100)  # -10.4 g
        self.assertAlmostEqual(spaghetti.effect.cost, (200 * 0.4 - 200 * 0.5) / 100)         # -$0.20
        self.assertAlmostEqual(spaghetti.effect.nutrients[0][2], 6.0)
        self.assertEqual((udon.effect.cost, udon.effect.nutrients[0][2]), (None, None))
        text = describe(alts)
        self.assertIn("Rice Noodles (the recipe's own rule, 0.8 for 1): 160 g for e2; +$0.60; Protein -10.4 g", text)
        self.assertIn("Udon (one to one by weight; not checked against the recipe)", text)

    def test_food_on_hand_comes_first_and_a_food_a_recipe_rules_out_is_not_suggested(self):
        g = kitchen()
        rule(g, "in0 pasta or 2 Udon", "in0 pasta", "Udon", 1.0, excluded=True)
        rule(g, "in0 pasta or 3 Spaghetti", "in0 pasta", "Spaghetti", 1.0)
        add_portion(g, "spaghetti on hand", "Spaghetti", 120.0)
        alts = alternatives(g, "week", "Noodles", NOW, None, PROTEIN)
        self.assertEqual([(a.kind, a.food, a.have) for a in alts.options],
                         [("same", None, 0.0), ("recipe", "Spaghetti", 120.0), ("recipe", "Rice Noodles", 0.0),
                          ("replan", None, 0.0)])

    def test_the_same_foods_kinds_and_a_meal_swapped_already_needs_nothing(self):
        g = kitchen()
        add_type(g, "Egg Noodles", "Noodles")
        same = alternatives(g, "week", "Noodles", NOW, None, PROTEIN).options[0]
        self.assertEqual(same.kinds, ["Egg Noodles"])
        use_instead(g, "week", "Noodles", "Spaghetti")
        self.assertEqual(alternatives(g, "week", "Noodles", NOW, None, PROTEIN).meals, [])


if __name__ == "__main__":
    unittest.main()
