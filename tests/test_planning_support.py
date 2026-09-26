"""The engine changes the planner rests on: provenance-aware nutrition, stock as lots, pools by policy."""

import unittest
from datetime import timedelta

from mealplanner.inventory import eligible_lots, eligible_on_hand_with_urgency
from mealplanner.nutrition_scope import nutrient_profile_record, serving_nutrient, serving_nutrient_amount
from mealplanner.reservation import stock_pools
from tests.fakegraph import FakeGraph, Ref, at, type_tree, when
from tests.planning_graph import add_portion, add_recipe, add_type, new_kitchen


class Provenance(unittest.TestCase):
    def kitchen(self, provenance):
        g = new_kitchen()
        add_recipe(g, "omelette", output_grams=400, protein_per_100g=12, provenance=provenance, yield_servings=2, minutes=35)
        return g

    def test_the_record_carries_the_provenance(self):
        g = self.kitchen("sourced")
        self.assertEqual(nutrient_profile_record(g, "omelette (dish)", "Protein"), (12, "sourced"))

    def test_a_sourced_figure_is_trusted(self):
        g = self.kitchen("sourced")
        amount, trusted = serving_nutrient(g, g.get_all("Plan", "omelette")["result"], "Protein")
        self.assertEqual((amount, trusted), (24.0, True))                # 400 g x 12/100 = 48 g, for 2 servings

    def test_a_placeholder_figure_is_used_but_not_trusted(self):
        g = self.kitchen("placeholder")
        amount, trusted = serving_nutrient(g, g.get_all("Plan", "omelette")["result"], "Protein")
        self.assertEqual((amount, trusted), (24.0, False))

    def test_an_unmarked_profile_is_untrusted_too(self):
        g = self.kitchen(None)
        del g.nodes["profile omelette"]["provenance"]
        self.assertFalse(serving_nutrient(g, g.get_all("Plan", "omelette")["result"], "Protein")[1])

    def test_the_old_reader_still_returns_just_the_amount(self):
        g = self.kitchen("placeholder")
        self.assertEqual(serving_nutrient_amount(g, g.get_all("Plan", "omelette")["result"], "Protein"), 24.0)

    def test_two_outputs_are_trusted_only_if_both_profiles_are(self):
        g = self.kitchen("sourced")
        add_type(g, "broth (dish)")
        g.add("NutrientProfile", "profile broth", forNutrient=Ref("Protein"), basis="per_100g", amount=2.0, provenance="placeholder")
        g.nodes["broth (dish)"]["nutrientProfilesAbout"].append(Ref("profile broth"))
        g.add("QuantitySpecification", "q broth", value=500.0, unit="g")
        g.add("Specification", "out broth", hasParticipationRole="output", specifies=Ref("broth (dish)"),
              hasSpecifiedQuantity=Ref("q broth"), isOptional=False)
        g.nodes["step omelette"]["hasSpecification"].append(Ref("out broth"))
        amount, trusted = serving_nutrient(g, g.get_all("Plan", "omelette")["result"], "Protein")
        self.assertEqual(amount, (48.0 + 10.0) / 2)                      # 48 g + 500 g x 2/100 = 58 g, for 2 servings
        self.assertFalse(trusted)

    def test_no_profile_at_all_is_unknown_and_untrusted(self):
        g = self.kitchen("sourced")
        g.nodes["omelette (dish)"]["nutrientProfilesAbout"].clear()
        self.assertEqual(serving_nutrient(g, g.get_all("Plan", "omelette")["result"], "Protein"), (None, False))


class Lots(unittest.TestCase):
    """Stock as individual lots: soonest expiry first, with the expiry as a moment."""

    def graph(self):
        g = FakeGraph()
        type_tree(g, {"Chicken": {}})
        for name in ("Mass", "ShelfLife", "Fridge", "Sealed"):
            g.add("DomainType", name, name, defaultSpecifications=[], parent=None, children=[])
        g.add("DomainType", "Fresh Meat", "Fresh Meat", defaultSpecifications=[Ref("ds")], parent=None, children=[])
        g.add("QuantitySpecification", "five", value=5.0, unit="days")
        g.add("DefaultSpecification", "ds", hasKind=Ref("ShelfLife"), keyedBy=[Ref("Fridge"), Ref("Sealed")], hasValue=Ref("five"))
        for name, day, grams in (("a", 20, 300.0), ("b", 23, 200.0), ("c", 18, 500.0), ("d", 26, 100.0)):
            g.add("PortionOfSubstance", name, name, instanceOf=Ref("Chicken"), hasPerishabilityType=Ref("Fresh Meat"),
                  bearerOf=[Ref(f"q{name}")], allocationsAbout=[])
            g.add("Quality", f"q{name}", hasKind=Ref("Mass"), inheresIn=Ref(name), measurements=[Ref(f"m{name}")])
            g.add("Measurement", f"m{name}", status="observed", hasTime=at(day, 0), value=grams, unit="g")
        return g

    def test_lots_come_soonest_expiring_first_and_skip_the_expired(self):
        g = self.graph()
        lots = eligible_lots(g, "Chicken", when(24))
        # weighed on the 20th, 23rd, 18th, 26th; each keeps 5 days: expires the 25th, 28th, 23rd (already expired), 31st
        self.assertEqual([(lot.name, lot.grams) for lot in lots], [("a", 300.0), ("b", 200.0)])

    def test_a_future_weighing_is_not_stock_yet(self):
        g = self.graph()
        names = [lot.name for lot in eligible_lots(g, "Chicken", when(24))]
        self.assertNotIn("d", names)

    def test_the_expiry_is_now_plus_the_days_left(self):
        lot = eligible_lots(self.graph(), "Chicken", when(24))[0]
        self.assertAlmostEqual(lot.days_until_expiry, 1.0)
        self.assertEqual(lot.expires, when(24) + timedelta(days=1))

    def test_the_old_totals_are_the_sums_of_the_lots(self):
        g = self.graph()
        total, soonest = eligible_on_hand_with_urgency(g, "Chicken", when(24))
        self.assertEqual((total, soonest), (500.0, 1.0))


class Pools(unittest.TestCase):
    def graph(self):
        g = FakeGraph()
        type_tree(g, {"Flour": {"Bread Flour": {}}, "Rice": {}})
        for name in ("Mass",):
            g.add("DomainType", name, name, defaultSpecifications=[], parent=None, children=[])
        for name, target in (("Flour", 2000.0), ("Bread Flour", 1000.0)):
            g.add("QuantitySpecification", f"t-{name}", value=target, unit="g")
            g.add("StockPolicy", f"p-{name}", name=f"policy {name}", appliesTo=Ref(name), includesSubtypes=True,
                  hasTargetLevel=Ref(f"t-{name}"))
            g.nodes[name]["stockPoliciesApplying"].append(Ref(f"p-{name}"))
        add_portion(g, "flour a", "Flour", 300.0)
        add_portion(g, "bread a", "Bread Flour", 700.0)
        add_portion(g, "rice a", "Rice", 900.0)
        return g

    def test_each_type_draws_from_the_pool_of_the_policy_that_governs_it(self):
        pool_of, _ = stock_pools(self.graph(), {"Flour", "Bread Flour", "Rice"}, when(28))
        self.assertEqual(pool_of, {"Flour": "Flour", "Bread Flour": "Bread Flour", "Rice": "Rice"})

    def test_a_type_under_a_policy_uses_its_ancestors_pool_if_it_has_none_of_its_own(self):
        g = self.graph()
        add_type(g, "Rye Flour", "Flour")
        pool_of, _ = stock_pools(g, {"Rye Flour"}, when(28))
        self.assertEqual(pool_of["Rye Flour"], "Flour")

    def test_the_nested_policy_owns_its_stock(self):
        _, lots = stock_pools(self.graph(), {"Flour", "Bread Flour"}, when(28))
        self.assertEqual([lot.grams for lot in lots["Flour"]], [300.0])          # the bread flour is not counted twice
        self.assertEqual([lot.grams for lot in lots["Bread Flour"]], [700.0])

    def test_a_type_with_no_policy_is_its_own_pool_with_its_own_stock(self):
        _, lots = stock_pools(self.graph(), {"Rice"}, when(28))
        self.assertEqual([lot.grams for lot in lots["Rice"]], [900.0])


if __name__ == "__main__":
    unittest.main()
