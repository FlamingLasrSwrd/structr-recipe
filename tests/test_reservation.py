"""Reservation arithmetic, stock pools and policy combination, offline.
eligible_on_hand_with_urgency is replaced by a function over a plain dict of
stock, so these test the pooling logic and nothing about inventory."""

import unittest
from unittest import mock

from mealplanner import reservation
from mealplanner.reservation import (
    Reserved, available_for_planning, combine_policy_fields, committed_requirements, net_requirements,
)
from mealplanner.unit_conversion import QuantityError
from mealplanner.typetree import subtypes_of
from tests.fakegraph import FakeGraph, Ref, type_tree, when


def stock_function(graph, stock, calls=None):
    """A stand-in for eligible_on_hand_with_urgency over {type: grams}."""
    def fake(client, type_id, now, *, include_subtypes=True, exclude_types=None, **_filters):
        if calls is not None:
            calls.append(type_id)
        types = subtypes_of(graph, type_id) if include_subtypes else {type_id}
        for excluded in exclude_types or ():
            types -= subtypes_of(graph, excluded)
        return sum(stock.get(t, 0.0) for t in types), None
    return fake


class AvailabilityAcrossTheTypeTree(unittest.TestCase):
    def setUp(self):
        self.g = FakeGraph()
        type_tree(self.g, {"Poultry": {"Chicken": {}, "Turkey": {}}})
        self.stock = {"Chicken": 500.0, "Turkey": 500.0}
        self.calls = []

    def available(self, type_id, reserved_by_type, **filters):
        reserved = Reserved.from_by_type(self.g, reserved_by_type)
        eligible = sum(self.stock.get(t, 0.0) for t in subtypes_of(self.g, type_id)) if filters.get("include_subtypes", True) else self.stock.get(type_id, 0.0)
        with mock.patch.object(reservation, "eligible_on_hand_with_urgency", stock_function(self.g, self.stock, self.calls)):
            return available_for_planning(self.g, type_id, eligible, when(25), reserved, **filters)

    def test_a_generic_demand_sees_a_reservation_made_against_a_subtype(self):
        # 1000 g of poultry, 500 g reserved for chicken: a Poultry demand has 500 left, not 1000
        self.assertEqual(self.available("Poultry", {"Chicken": 500.0}), 500.0)

    def test_a_subtype_demand_sees_a_reservation_made_against_the_generic_type(self):
        # 600 g reserved for "some poultry": chicken (500 g) and turkey (500 g) share what is left
        self.assertEqual(self.available("Chicken", {"Poultry": 600.0}), 400.0)

    def test_a_small_generic_reservation_does_not_needlessly_reduce_a_subtype(self):
        # 400 g of generic poultry can come out of the turkey, so all 500 g of chicken is still free
        self.assertEqual(self.available("Chicken", {"Poultry": 400.0}), 500.0)

    def test_the_other_subtype_is_unaffected_by_a_sibling_reservation(self):
        # the turkey is all there for a turkey demand; only the shared pool is tighter
        self.assertEqual(self.available("Turkey", {"Chicken": 500.0}), 500.0)

    def test_a_sibling_reservation_can_tighten_the_shared_pool(self):
        self.stock = {"Chicken": 500.0, "Turkey": 500.0}
        self.assertEqual(self.available("Turkey", {"Chicken": 500.0, "Turkey": 300.0}), 200.0)

    def test_no_outside_claim_means_no_ancestor_stock_scan(self):
        self.available("Chicken", {"Chicken": 100.0})
        self.assertEqual(self.calls, [])            # the shortcut: nothing to compare against above

    def test_an_exact_only_policy_ignores_claims_below_it(self):
        # 300 g held as plain "Poultry"; a chicken reservation is drawn from the chicken, not from that
        self.stock["Poultry"] = 300.0
        self.assertEqual(self.available("Poultry", {"Chicken": 500.0}, include_subtypes=False), 300.0)
        # ...whereas the same claim does reduce a policy that counts the whole subtree (300 + 500 + 500 - 500)
        self.assertEqual(self.available("Poultry", {"Chicken": 500.0}), 800.0)

    def test_availability_never_goes_negative(self):
        self.assertEqual(self.available("Chicken", {"Chicken": 900.0}), 0.0)


class NestedPoliciesDoNotDoubleCount(unittest.TestCase):
    def build(self, stock):
        g = FakeGraph()
        type_tree(g, {"Flour": {"Bread Flour": {}}})
        g.add("DomainType", "Grain", "Grain", parent=None, children=[], stockPoliciesApplying=[], defaultSpecifications=[])
        for name, target in (("Flour", 2000.0), ("Bread Flour", 1000.0)):
            g.add("QuantitySpecification", f"t-{name}", value=target, unit="g")
            g.add("StockPolicy", f"p-{name}", name=f"policy {name}", appliesTo=Ref(name), includesSubtypes=True,
                  hasTargetLevel=Ref(f"t-{name}"))
            g.nodes[name]["stockPoliciesApplying"].append(Ref(f"p-{name}"))
        return g

    def run_net(self, stock):
        g = self.build(stock)
        with mock.patch.object(reservation, "eligible_on_hand_with_urgency", stock_function(g, stock)), \
             mock.patch.object(reservation, "committed_requirements", lambda c, m: {}):
            return net_requirements(g, "plan", when(25))

    def test_the_nested_policy_owns_its_stock(self):
        # 2 kg of bread flour, "keep 2 kg flour" and "keep 1 kg bread flour". The bread flour meets ITS target
        # and leaves none for the ancestor's, which still needs 2 kg.
        self.assertEqual(self.run_net({"Bread Flour": 2000.0}), {"Flour": 2000.0})

    def test_stock_of_the_ancestor_itself_still_counts_for_the_ancestor(self):
        self.assertEqual(self.run_net({"Bread Flour": 1000.0, "Flour": 1500.0}), {"Flour": 500.0})

    def test_a_pool_short_of_its_own_target_is_reported_under_that_pool(self):
        self.assertEqual(self.run_net({"Bread Flour": 400.0, "Flour": 2000.0}), {"Bread Flour": 600.0})


class RestrictiveCombination(unittest.TestCase):
    A = {"eligibleWhenOpened": None, "eligibleWhenSealed": True, "storage": {"Fridge"}, "includesSubtypes": True}
    B = {"eligibleWhenOpened": False, "eligibleWhenSealed": None, "storage": {"Fridge", "Pantry"}, "includesSubtypes": None}

    def test_order_does_not_matter(self):
        self.assertEqual(combine_policy_fields([self.A, self.B]), combine_policy_fields([self.B, self.A]))

    def test_flags_and_storage_only_ever_shrink(self):
        combined = combine_policy_fields([self.A, self.B])
        self.assertEqual((combined["eligibleWhenOpened"], combined["eligibleWhenSealed"], combined["storage"]), (False, True, {"Fridge"}))

    def test_disjoint_storage_leaves_nothing_eligible(self):
        other = {"eligibleWhenOpened": None, "eligibleWhenSealed": None, "storage": {"Freezer"}, "includesSubtypes": False}
        combined = combine_policy_fields([self.A, other])
        self.assertEqual(combined["storage"], set())
        self.assertFalse(combined["includesSubtypes"])


class CommittedRequirementsScaleByServings(unittest.TestCase):
    """planned servings / recipe yield, Sec 7. Recipe: 400 g chicken for a yield of 4 servings."""

    def build(self, yield_value=4.0, yield_unit="servings", entries=None):
        g = FakeGraph()
        type_tree(g, {"Chicken": {}})
        g.add("QuantitySpecification", "q_chicken", value=400.0, unit="g")
        g.add("Specification", "spec", hasParticipationRole="input", specifies=Ref("Chicken"), hasSpecifiedQuantity=Ref("q_chicken"))
        g.add("Step", "step", hasSpecification=[Ref("spec")])
        plan = dict(steps=[Ref("step")])
        if yield_value is not None:
            g.add("QuantitySpecification", "q_yield", value=yield_value, unit=yield_unit)
            plan["hasRecipeYield"] = Ref("q_yield")
        g.add("Plan", "plan", "Chicken dinner", **plan)
        entries = entries or [dict(hasPlannedServings=2.0)]
        for i, props in enumerate(entries):
            g.add("MealPlanEntry", f"e{i}", f"entry {i}", references=Ref("plan"), **props)
        g.add("MealPlan", "week", hasEntry=[Ref(f"e{i}") for i in range(len(entries))])
        return g

    def test_planning_half_the_recipe_claims_half_the_ingredients(self):
        # 2 servings planned of a recipe for 4: 400 x 2 / 4 = 200 g
        self.assertEqual(committed_requirements(self.build(), "week"), {"Chicken": 200.0})

    def test_two_entries_add(self):
        g = self.build(entries=[dict(hasPlannedServings=2.0), dict(hasPlannedServings=6.0)])
        self.assertEqual(committed_requirements(g, "week"), {"Chicken": 200.0 + 600.0})

    def test_skipped_and_fulfilled_entries_claim_nothing(self):
        g = self.build(entries=[dict(hasPlannedServings=2.0, isSkipped=True), dict(hasPlannedServings=2.0, fulfilledBy=Ref("done"))])
        g.add("Process", "done")
        self.assertEqual(committed_requirements(g, "week"), {})

    def test_an_unstated_yield_is_an_error_not_one_serving(self):
        # the old code took the yield as 1 and claimed 400 x 2 / 1 = 800 g
        with self.assertRaisesRegex(QuantityError, "entry 0"):
            committed_requirements(self.build(yield_value=None), "week")

    def test_a_yield_that_is_not_in_servings_is_an_error(self):
        with self.assertRaises(QuantityError):
            committed_requirements(self.build(yield_unit="batch"), "week")

    def test_a_zero_yield_is_an_error_not_silently_skipped(self):
        with self.assertRaises(QuantityError):
            committed_requirements(self.build(yield_value=0.0), "week")


if __name__ == "__main__":
    unittest.main()
