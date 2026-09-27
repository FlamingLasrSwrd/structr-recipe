"""Nutrient units (J17) and nutrition worked out from a recipe's ingredients (Sec 8 rule 7(b), J18).

The kitchen, and the figures worked out by hand from it:

  stew: one Braising Step, 500 g Beef + 200 g Carrot, 4 servings; the dish has no profile.
      Beef    protein 20 g/100 g   energy 250 kcal/100 g   vitamin C 0 mg/100 g
      Carrot  protein  1 g/100 g   energy 171.544 kJ/100 g (= 41 kcal)   vitamin C 5.9 mg/100 g
  protein per serving   (500 x 20/100 + 200 x 1/100) / 4 = (100 + 2) / 4       = 25.5 g
  energy per serving    (500 x 250/100 + 200 x 41/100) / 4 = (1250 + 82) / 4  = 333 kcal = 1393.272 kJ
  vitamin C, carrot retaining half when braised: 200 x 5.9/100 x 0.5 / 4      = 1.475 mg
"""

import unittest

from mealplanner.nutrition_scope import (
    AmbiguousProfileError, NutrientUnitError, convert_nutrient, nutrition_report, serving_nutrient,
    serving_nutrient_figure,
)
from tests.fakegraph import FakeGraph, Ref, at


def add_type(g, name, parent=None):
    g.add("DomainType", name, name, parent=Ref(parent) if parent else None, children=[], defaultSpecifications=[],
          nutrientProfilesAbout=[])
    if parent:
        g.nodes[parent]["children"].append(Ref(name))


def profile(g, food, nutrient, amount, unit, provenance="sourced"):
    pid = f"profile {food} {nutrient}"
    g.add("NutrientProfile", pid, forNutrient=Ref(nutrient), basis="per_100g", amount=amount, unit=unit,
          provenance=provenance)
    g.nodes[food]["nutrientProfilesAbout"].append(Ref(pid))


def retention(g, food, nutrient, value, *keys, unit="ratio"):
    did = f"retention {food} {nutrient} {'+'.join(keys)}"
    g.add("QuantitySpecification", f"q {did}", value=value, unit=unit)
    g.add("DefaultSpecification", did, hasKind=Ref("RetentionFactor"), keyedBy=[Ref(k) for k in (nutrient, *keys)],
          hasValue=Ref(f"q {did}"))
    g.nodes[food]["defaultSpecifications"].append(Ref(did))


def spec(g, sid, role, food, grams=None, optional=False):
    fields = dict(hasParticipationRole=role, specifies=Ref(food), isOptional=optional)
    if grams is not None:
        g.add("QuantitySpecification", f"q {sid}", value=grams, unit="g")
        fields["hasSpecifiedQuantity"] = Ref(f"q {sid}")
    g.add("Specification", sid, **fields)
    return Ref(sid)


def kitchen():
    g = FakeGraph()
    for name in ("Protein", "Energy", "Vitamin C", "Sodium", "RetentionFactor", "Braising", "Boiling"):
        add_type(g, name)
    add_type(g, "Food")
    for food in ("Beef", "Carrot", "Stew", "Salt", "Parsley", "Braised beef"):
        add_type(g, food, "Food")
    profile(g, "Beef", "Protein", 20.0, "g")
    profile(g, "Beef", "Energy", 250.0, "kcal")
    profile(g, "Beef", "Vitamin C", 0.0, "mg")
    profile(g, "Carrot", "Protein", 1.0, "g")
    profile(g, "Carrot", "Energy", 171.544, "kJ")
    profile(g, "Carrot", "Vitamin C", 5.9, "mg")
    g.add("Step", "braise", instanceOf=Ref("Braising"), hasSpecification=[
        spec(g, "in beef", "input", "Beef", 500.0), spec(g, "in carrot", "input", "Carrot", 200.0),
        spec(g, "out stew", "output", "Stew")])
    g.add("QuantitySpecification", "yield", value=4.0, unit="servings")
    g.add("Plan", "stew", "stew", steps=[Ref("braise")], hasRecipeYield=Ref("yield"))
    return g


def stew(g):
    return g.get_all("Plan", "stew")["result"]


def conserved(g, *nutrients):
    """A factor of 1 for these nutrients on the root, for every food and every method."""
    for nutrient in nutrients:
        retention(g, "Food", nutrient, 1.0)


class Units(unittest.TestCase):
    def test_within_a_dimension(self):
        self.assertAlmostEqual(convert_nutrient(2.3, "g", "mg"), 2300.0)
        self.assertAlmostEqual(convert_nutrient(150.0, "ug", "mg"), 0.15)
        self.assertAlmostEqual(convert_nutrient(100.0, "kcal", "kJ"), 418.4)
        self.assertEqual(convert_nutrient(400.0, "IU", "IU"), 400.0)

    def test_across_dimensions_is_not_a_number(self):
        self.assertIsNone(convert_nutrient(1.0, "g", "kcal"))
        self.assertIsNone(convert_nutrient(1.0, "IU", "ug"))

    def test_an_unknown_unit_raises(self):
        with self.assertRaises(NutrientUnitError):
            convert_nutrient(1.0, "cup", "g")
        with self.assertRaises(NutrientUnitError):
            convert_nutrient(1.0, None, "g")


class FromIngredients(unittest.TestCase):
    def test_protein_is_the_ingredients_sum_per_serving(self):
        figure = serving_nutrient_figure(kitchen(), stew(kitchen()), "Protein")
        self.assertAlmostEqual(figure.amount, 25.5)
        self.assertEqual(figure.method, "ingredients")

    def test_without_retention_factors_it_is_counted_whole_as_an_estimate(self):
        figure = serving_nutrient_figure(kitchen(), stew(kitchen()), "Protein")
        self.assertTrue(figure.trusted and figure.estimated)             # J21: usable, and said to be an estimate
        self.assertEqual(figure.unadjusted, ("Beef", "Carrot"))
        self.assertIn("no retention factor", figure.reason)

    def test_a_conserved_nutrient_from_sourced_profiles_is_not_an_estimate(self):
        g = kitchen()
        conserved(g, "Protein")
        figure = serving_nutrient_figure(g, stew(g), "Protein")
        self.assertEqual((figure.trusted, figure.estimated, figure.reason), (True, False, None))

    def test_an_estimated_or_calculated_profile_is_usable_and_flagged(self):
        for provenance in ("estimated", "calculated"):
            g = kitchen()
            conserved(g, "Protein")
            g.nodes["profile Carrot Protein"]["provenance"] = provenance
            figure = serving_nutrient_figure(g, stew(g), "Protein")
            self.assertEqual((figure.trusted, figure.estimated), (True, True), provenance)
            self.assertIn(provenance, figure.reason)

    def test_a_conserved_nutrient_from_sourced_profiles_is_trusted(self):
        g = kitchen()
        conserved(g, "Protein")
        amount, trusted = serving_nutrient(g, stew(g), "Protein")
        self.assertAlmostEqual(amount, 25.5)
        self.assertTrue(trusted)

    def test_one_placeholder_ingredient_makes_it_untrusted(self):
        g = kitchen()
        conserved(g, "Protein")
        g.nodes["profile Carrot Protein"]["provenance"] = "placeholder"
        self.assertFalse(serving_nutrient(g, stew(g), "Protein")[1])

    def test_energy_mixes_kcal_and_kj_profiles(self):
        g = kitchen()
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Energy", "kcal")[0], 333.0)
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Energy", "kJ")[0], 1393.272)

    def test_a_retention_factor_for_the_steps_method_applies(self):
        g = kitchen()
        retention(g, "Carrot", "Vitamin C", 0.5, "Braising")
        figure = serving_nutrient_figure(g, stew(g), "Vitamin C", "mg")
        self.assertAlmostEqual(figure.amount, 1.475)
        self.assertEqual(figure.unadjusted, ())         # beef has none to lose, so it needs no factor
        self.assertTrue(figure.trusted)

    def test_a_factor_for_another_method_does_not(self):
        g = kitchen()
        retention(g, "Carrot", "Vitamin C", 0.5, "Boiling")
        figure = serving_nutrient_figure(g, stew(g), "Vitamin C", "mg")
        self.assertAlmostEqual(figure.amount, 200 * 5.9 / 100 / 4)
        self.assertEqual(figure.unadjusted, ("Carrot",))

    def test_a_food_level_factor_beats_the_roots(self):
        g = kitchen()
        conserved(g, "Vitamin C")
        retention(g, "Carrot", "Vitamin C", 0.5, "Braising")
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Vitamin C", "mg")[0], 1.475)

    def test_a_factor_not_keyed_by_its_nutrient_is_malformed(self):
        g = kitchen()
        g.add("QuantitySpecification", "q bad", value=0.5, unit="ratio")
        g.add("DefaultSpecification", "bad", hasKind=Ref("RetentionFactor"), keyedBy=[Ref("Braising")], hasValue=Ref("q bad"))
        g.nodes["Carrot"]["defaultSpecifications"].append(Ref("bad"))
        with self.assertRaises(ValueError):
            serving_nutrient(g, stew(g), "Protein")

    def test_a_factor_that_is_not_a_ratio_is_malformed(self):
        g = kitchen()
        retention(g, "Carrot", "Protein", 50.0, unit="percent")
        with self.assertRaises(ValueError):
            serving_nutrient(g, stew(g), "Protein")

    def test_an_ingredient_without_a_profile_makes_it_unknown(self):
        g = kitchen()
        figure = serving_nutrient_figure(g, stew(g), "Sodium", "mg")
        self.assertIsNone(figure.amount)
        self.assertIn("Beef", figure.reason)

    def test_an_unquantified_ingredient_is_unknown_only_where_it_has_some(self):
        g = kitchen()
        profile(g, "Beef", "Sodium", 60.0, "mg")
        profile(g, "Carrot", "Sodium", 69.0, "mg")
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Sodium", "mg")[0], (300.0 + 138.0) / 4)
        profile(g, "Salt", "Sodium", 38758.0, "mg")
        profile(g, "Salt", "Protein", 0.0, "g")
        g.nodes["braise"]["hasSpecification"].append(spec(g, "in salt", "input", "Salt"))      # "salt to taste"
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Protein")[0], 25.5)
        figure = serving_nutrient_figure(g, stew(g), "Sodium", "mg")
        self.assertIsNone(figure.amount)
        self.assertIn("Salt", figure.reason)

    def test_an_optional_ingredient_is_left_out(self):
        g = kitchen()
        profile(g, "Parsley", "Protein", 3.0, "g")
        g.nodes["braise"]["hasSpecification"].append(spec(g, "in parsley", "input", "Parsley", 10.0, optional=True))
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Protein")[0], 25.5)

    def test_an_intermediate_is_not_counted_again(self):
        g = kitchen()
        profile(g, "Braised beef", "Protein", 27.0, "g")       # its own figure is not used either
        g.nodes["braise"]["hasSpecification"] = [spec(g, "in beef", "input", "Beef", 500.0),
                                                 spec(g, "out braised", "output", "Braised beef")]
        g.add("Step", "finish", instanceOf=Ref("Boiling"), hasSpecification=[
            spec(g, "in braised", "input", "Braised beef", 375.0), spec(g, "in carrot 2", "input", "Carrot", 200.0),
            spec(g, "out stew 2", "output", "Stew")])
        g.nodes["stew"]["steps"].append(Ref("finish"))
        self.assertAlmostEqual(serving_nutrient(g, stew(g), "Protein")[0], 25.5)

    def test_each_ingredient_takes_the_factor_of_the_step_it_enters(self):
        g = kitchen()
        retention(g, "Carrot", "Vitamin C", 0.5, "Braising")
        g.nodes["braise"]["hasSpecification"] = [spec(g, "in beef", "input", "Beef", 500.0),
                                                 spec(g, "out braised", "output", "Braised beef")]
        g.add("Step", "finish", instanceOf=Ref("Boiling"), hasSpecification=[
            spec(g, "in braised", "input", "Braised beef", 375.0), spec(g, "in carrot 2", "input", "Carrot", 200.0),
            spec(g, "out stew 2", "output", "Stew")])
        g.nodes["stew"]["steps"].append(Ref("finish"))
        figure = serving_nutrient_figure(g, stew(g), "Vitamin C", "mg")
        self.assertEqual(figure.unadjusted, ("Carrot",))    # it is boiled here, and the factor is for braising

    def test_no_ingredients_is_unknown_not_zero(self):
        g = kitchen()
        g.nodes["braise"]["hasSpecification"] = [spec(g, "out only", "output", "Stew")]
        self.assertEqual(serving_nutrient(g, stew(g), "Protein"), (None, False))

    def test_a_profile_in_another_dimension_is_unknown(self):
        g = kitchen()
        g.nodes["profile Carrot Protein"]["unit"] = "IU"
        self.assertIsNone(serving_nutrient(g, stew(g), "Protein")[0])

    def test_a_profile_without_a_unit_raises(self):
        g = kitchen()
        del g.nodes["profile Carrot Protein"]["unit"]
        with self.assertRaises(NutrientUnitError):
            serving_nutrient(g, stew(g), "Protein")

    def test_two_profiles_for_one_nutrient_raise(self):
        g = kitchen()
        g.add("NutrientProfile", "second", forNutrient=Ref("Protein"), basis="per_100g", amount=2.0, unit="g",
              provenance="sourced")
        g.nodes["Carrot"]["nutrientProfilesAbout"].append(Ref("second"))
        with self.assertRaises(AmbiguousProfileError):
            serving_nutrient(g, stew(g), "Protein")


class DishFirst(unittest.TestCase):
    def dish_profile(self, g, grams):
        profile(g, "Stew", "Protein", 10.0, "g")
        if grams is not None:
            g.add("QuantitySpecification", "q stew out", value=grams, unit="g")
            g.nodes["out stew"]["hasSpecifiedQuantity"] = Ref("q stew out")

    def test_the_dishs_own_profile_wins_when_it_has_a_mass(self):
        g = kitchen()
        self.dish_profile(g, 600.0)
        figure = serving_nutrient_figure(g, stew(g), "Protein")
        self.assertEqual((figure.method, figure.amount), ("dish", 600 * 10 / 100 / 4))

    def test_without_a_mass_it_falls_back_to_the_ingredients(self):
        g = kitchen()
        self.dish_profile(g, None)
        figure = serving_nutrient_figure(g, stew(g), "Protein")
        self.assertEqual(figure.method, "ingredients")
        self.assertAlmostEqual(figure.amount, 25.5)

    def test_two_outputs_without_profiles_are_unknown(self):
        g = kitchen()
        add_type(g, "Broth", "Food")
        g.nodes["braise"]["hasSpecification"].append(spec(g, "out broth", "output", "Broth"))
        figure = serving_nutrient_figure(g, stew(g), "Protein")
        self.assertIsNone(figure.amount)
        self.assertIn("several final outputs", figure.reason)


class Report(unittest.TestCase):
    def test_a_daily_energy_target_in_kcal(self):
        g = kitchen()
        g.add("QuantitySpecification", "range", minValue=1800.0, maxValue=2500.0, unit="kcal")
        g.add("NutritionTarget", "energy", "energy", forNutrient=Ref("Energy"), hasTargetRange=Ref("range"),
              hasTimeScope="daily", dayBoundaryRule="midnight", strictness="soft")
        g.add("MealPlan", "week", "week", hasEntry=[], hasConstraint=[Ref("energy")])
        for i, hour in enumerate((12, 18)):
            g.add("TemporalRegion", f"r{i}", hasBeginning=at(28, hour))
            g.add("MealPlanEntry", f"e{i}", f"e{i}", isAbout=Ref(f"r{i}"), isSkipped=False, references=Ref("stew"),
                  memberOf=Ref("week"))
            g.nodes["week"]["hasEntry"].append(Ref(f"e{i}"))
        (row,) = nutrition_report(g, "week")
        self.assertEqual((row["unit"], row["status"]), ("kcal", "below_min"))
        self.assertAlmostEqual(row["total"], 666.0)          # two servings of 333 kcal


if __name__ == "__main__":
    unittest.main()
