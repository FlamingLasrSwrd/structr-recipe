"""A committed week's shopping list (mealplanner/shopping.py, tools/shopping_list.py).

Worked by hand on tests/test_planning_extract.py's kitchen: an omelette (yield 2) takes 300 g of
eggs; pasta (yield 2) takes 200 g of noodles and 100 g of eggs. Monday's omelette is cooked for 4
servings, so 600 g of eggs; Tuesday's pasta for 2, so 200 g of noodles and 100 g of eggs; Wednesday
eats Monday's leftovers, which need nothing. 250 g of eggs are on hand: buy 450 g of eggs and 200 g
of noodles. The omelette also takes salt, with no amount.
"""

import unittest
from datetime import timezone
from types import SimpleNamespace

from mealplanner.shopping import Line, describe, shopping_list
from tests.fakegraph import Ref, at, when
from tests.planning_graph import add_entry, add_portion, add_type
from tests.test_planning_extract import kitchen

NOW = when(25, 0)


def week(eggs_on_hand=250.0):
    g = kitchen()
    for name, plan, day, servings in (("e1", "omelette", 28, 4.0), ("e2", "pasta", 29, 2.0)):
        add_entry(g, name, plan, at(day, 18), servings=servings)
    add_entry(g, "e3", None, at(30, 18), leftover_of="e1")
    add_portion(g, "eggs on hand", "Eggs", eggs_on_hand)
    add_type(g, "Salt")
    g.add("Specification", "salt omelette", hasParticipationRole="input", specifies=Ref("Salt"), isOptional=False)
    g.nodes["step omelette"]["hasSpecification"].append(Ref("salt omelette"))
    return g


def priced(**per_100g):
    return {food: SimpleNamespace(quantity={"value": value}, spec={"provenance": "sourced"}) for food, value in per_100g.items()}


class TheList(unittest.TestCase):
    def test_what_to_buy_what_is_on_hand_and_when_it_is_first_needed(self):
        shopping = shopping_list(week(), "week", NOW)
        self.assertEqual((shopping.cooks, shopping.leftovers), (2, 1))
        lines = {line.food: line for line in shopping.to_buy}
        eggs, noodles = lines["Eggs"], lines["Noodles"]
        self.assertEqual((eggs.need, eggs.have, eggs.buy, eggs.first_needed, eggs.recipes),
                         (700.0, 250.0, 450.0, when(28, 18), ["omelette", "pasta"]))
        self.assertEqual((noodles.need, noodles.buy, noodles.first_needed), (200.0, 200.0, when(29, 18)))
        self.assertEqual(shopping.covered, [])
        self.assertEqual(shopping.unquantified, {"Salt": ["omelette"]})

    def test_a_food_one_recipe_gives_an_amount_is_on_the_list_not_in_the_note(self):
        g = week()
        g.add("Specification", "eggs to taste", hasParticipationRole="input", specifies=Ref("Eggs"), isOptional=False)
        g.nodes["step pasta"]["hasSpecification"].append(Ref("eggs to taste"))
        shopping = shopping_list(g, "week", NOW)
        self.assertEqual(shopping.unquantified, {"Salt": ["omelette"]})
        self.assertIn("Eggs", [line.food for line in shopping.to_buy])

    def test_enough_on_hand_is_covered_not_bought(self):
        shopping = shopping_list(week(eggs_on_hand=900.0), "week", NOW)
        (covered,) = shopping.covered
        self.assertEqual((covered.food, covered.need, covered.have, covered.buy), ("Eggs", 700.0, 900.0, 0.0))
        self.assertEqual([line.food for line in shopping.to_buy], ["Noodles"])

    def test_costs_at_a_price_level_what_is_not_priced_and_what_costs_nothing(self):
        shopping = shopping_list(week(), "week", NOW, priced(Eggs=0.5))
        self.assertAlmostEqual(shopping.total, 450 * 0.5 / 100)
        self.assertEqual(shopping.unpriced, ["Noodles"])
        shopping = shopping_list(week(), "week", NOW, priced(Eggs=0.5, Noodles=0.0))   # as tap water is
        self.assertEqual(([line.food for line in shopping.to_buy], shopping.not_bought), (["Eggs"], ["Noodles"]))

    def test_a_skipped_or_cooked_meal_needs_nothing_more(self):
        g = week()
        g.nodes["e2"]["isSkipped"] = True
        g.nodes["e1"]["fulfilledBy"] = Ref("e1")              # cooked: its eggs are already out of stock
        shopping = shopping_list(g, "week", NOW)
        self.assertEqual((shopping.cooks, shopping.to_buy), (0, []))


class InWords(unittest.TestCase):
    def test_grouped_by_day_and_sorted_by_name(self):
        text = describe(shopping_list(week(), "week", NOW, priced(Eggs=0.5, Noodles=0.3)), timezone.utc, "Home prices")
        self.assertLess(text.index("First needed Mon 28 Sep:"), text.index("Eggs"))
        self.assertLess(text.index("Eggs"), text.index("First needed Tue 29 Sep:"))
        self.assertLess(text.index("First needed Tue 29 Sep:"), text.index("Noodles"))
        self.assertIn("have 250 g of 700 g", text)
        self.assertIn("About $2.85 at 'Home prices'", text)          # 450 g x $0.50 + 200 g x $0.30, per 100 g
        self.assertIn("No amount in the recipe, so check there is some: Salt (omelette)", text)

    def test_amounts_read_as_a_shopper_would(self):
        self.assertEqual(Line("Eggs", 450.0, 700.0, 250.0, each=50.0).amount(), "9 (about 450 g)")
        self.assertEqual(Line("Beef", 680.0, 680.0, 0.0).amount(), "680 g (1.5 lb)")
        self.assertEqual(Line("Peas", 150.0, 150.0, 0.0).amount(), "150 g (5.3 oz)")
        self.assertEqual(Line("Cumin", 2.0, 2.0, 0.0).amount(), "2 g")


if __name__ == "__main__":
    unittest.main()
