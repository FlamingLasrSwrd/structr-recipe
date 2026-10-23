"""convert_to_grams(): what a recipe's cups, spoons and counts weigh (invariant 13; unit_conversion.py).

Worked by hand. Milk has a density of 1.03 g per mL, so a cup (236.588 mL) of it is 243.686 g; skim
milk has no density of its own and takes milk's, up the hierarchy. An egg weighs 50 g. The table is
checked against relations that hold whatever its figures (16 tablespoons a cup, 3 teaspoons a
tablespoon, 16 ounces a pound), so a slip in one figure shows.
"""

import unittest

from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from tests.fakegraph import FakeGraph, Ref, type_tree


def kitchen(density_unit="g_per_mL"):
    g = FakeGraph()
    type_tree(g, {"Food": {"Milk": {"Skim milk": {}}, "Egg": {}, "Flour": {}}})
    for kind in ("Density", "MassPerUnit"):
        g.add("DomainType", kind, kind, defaultSpecifications=[], parent=None, children=[])
    for i, (food, kind, value, unit) in enumerate((("Milk", "Density", 1.03, density_unit), ("Egg", "MassPerUnit", 50.0, "g_per_each"))):
        g.add("QuantitySpecification", f"q{i}", value=value, unit=unit)
        g.add("DefaultSpecification", f"d{i}", f"{food} {kind}", hasKind=Ref(kind), keyedBy=[], hasValue=Ref(f"q{i}"))
        g.nodes[food]["defaultSpecifications"].append(Ref(f"d{i}"))
    return g


def factor(unit):
    return UNIT_TABLE[unit][1]


class TheTable(unittest.TestCase):
    def test_masses(self):
        self.assertEqual((factor("g"), factor("gram"), factor("grams"), factor("kg"), factor("mg")), (1.0, 1.0, 1.0, 1000.0, 0.001))
        self.assertAlmostEqual(16 * factor("oz"), factor("lb"), places=2)
        self.assertAlmostEqual(factor("lb"), 453.592, places=3)

    def test_volumes(self):
        self.assertEqual((factor("ml"), factor("l")), (1.0, 1000.0))
        self.assertAlmostEqual(factor("cup"), 236.588, places=3)
        self.assertAlmostEqual(16 * factor("tbsp"), factor("cup"), places=2)
        self.assertAlmostEqual(3 * factor("tsp"), factor("tbsp"), places=3)
        self.assertAlmostEqual(2 * factor("tbsp"), factor("fl_oz"), places=3)
        self.assertAlmostEqual((8 * factor("dash"), 16 * factor("pinch")), (factor("tsp"), factor("tsp")))

    def test_counts_are_one_item_each(self):
        self.assertEqual({factor(u) for u in ("each", "whole", "count")}, {1.0})
        self.assertEqual({UNIT_TABLE[u][0] for u in ("each", "whole", "count")}, {"count"})


class Converting(unittest.TestCase):
    def test_a_mass_needs_no_food(self):
        self.assertAlmostEqual(convert_to_grams(kitchen(), None, 2, "lb"), 907.184)
        self.assertEqual(convert_to_grams(kitchen(), "Flour", 250, "mg"), 0.25)

    def test_a_volume_through_the_foods_density(self):
        g = kitchen()
        self.assertAlmostEqual(convert_to_grams(g, "Milk", 1, "cup"), 236.588 * 1.03)
        self.assertAlmostEqual(convert_to_grams(g, "Milk", 2, "tbsp"), 2 * 14.7868 * 1.03)

    def test_a_density_is_found_up_the_hierarchy(self):
        self.assertAlmostEqual(convert_to_grams(kitchen(), "Skim milk", 1, "l"), 1030.0)

    def test_a_count_through_the_weight_per_item(self):
        g = kitchen()
        self.assertEqual((convert_to_grams(g, "Egg", 3, "each"), convert_to_grams(g, "Egg", 1, "whole")), (150.0, 50.0))

    def test_without_what_it_needs_it_is_unconvertible_never_guessed(self):
        g = kitchen()
        self.assertIsNone(convert_to_grams(g, "Flour", 1, "cup"))          # no density
        self.assertIsNone(convert_to_grams(g, "Milk", 2, "each"))          # no weight per item
        self.assertIsNone(convert_to_grams(g, None, 1, "cup"))             # no food at all
        self.assertIsNone(convert_to_grams(g, "Milk", 1, "handful"))       # not a unit it knows
        self.assertIsNone(convert_to_grams(g, "Milk", 1, None))

    def test_a_density_in_the_wrong_unit_is_an_error(self):
        with self.assertRaises(ValueError):
            convert_to_grams(kitchen(density_unit="g_per_cup"), "Milk", 1, "cup")


if __name__ == "__main__":
    unittest.main()
