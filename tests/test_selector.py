"""Selector behaviour through select(), on a minimal in-memory graph: numbers
that are legitimately zero, exclusions by role, soft exclusions, and ordering."""

import importlib.util
import os
import unittest

os.environ.setdefault("STRUCTR_SUPERUSER_PASSWORD", "unused-in-tests")
_spec = importlib.util.spec_from_file_location(
    "selector_11c", os.path.join(os.path.dirname(__file__), "..", "scripts", "11c_simple_selector.py"))
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)

from tests.fakegraph import FakeGraph, Ref, type_tree, when


def kitchen(**meal_plan):
    g = FakeGraph()
    type_tree(g, {"Peanut": {}, "Almond": {}, "Flour": {}, "Whisk": {}, "Pasta": {}})
    g.add("MealPlan", "week", "week", hasEntry=[], hasConstraint=[], **meal_plan)
    return g


def recipe(g, name, specs, minutes=10.0):
    """specs: [(role, type, optional)]"""
    refs = []
    for i, (role, type_name, optional) in enumerate(specs):
        g.add("Specification", f"{name}-s{i}", hasParticipationRole=role, specifies=Ref(type_name), isOptional=optional)
        refs.append(Ref(f"{name}-s{i}"))
    g.add("Step", f"{name}-step", hasSpecification=refs)
    g.add("Plan", name, name, steps=[Ref(f"{name}-step")], estimatedDurationMinutes=minutes, referencedByEntries=[])
    return name


def exclusion(g, name, applies_to, strictness, weight=None):
    g.add("ExclusionConstraint", name, name, appliesTo=Ref(applies_to), strictness=strictness, weight=weight)


def rank(g):
    return {r["plan"]["name"]: r for r in sel.select(g, "week", when(25))}


class ZeroIsNotMissing(unittest.TestCase):
    def test_number_helper(self):
        self.assertEqual(sel._number(0, 0.5), 0)
        self.assertEqual(sel._number(0.0, 60.0), 0.0)
        self.assertEqual(sel._number(None, 0.5), 0.5)

    def test_a_zero_weight_is_respected_by_select(self):
        g = kitchen(timeBudgetMinutes=30.0, timeBudgetWeight=0.0, varietyWeight=0.0)
        recipe(g, "quick", [("input", "Flour", False)], minutes=10.0)
        # the old `weight or 0.5` turned this into 0.5 * 1.0 + 0.5 * 1.0 = 1.0
        self.assertEqual(rank(g)["quick"]["score"], 0.0)

    def test_a_default_still_applies_when_the_field_is_absent(self):
        g = kitchen(timeBudgetMinutes=30.0)
        recipe(g, "quick", [("input", "Flour", False)], minutes=10.0)
        self.assertEqual(rank(g)["quick"]["score"], 1.0)     # 0.5 * 1.0 + 0.5 * 1.0

    def test_a_zero_time_budget_does_not_divide_by_zero(self):
        self.assertEqual(sel.time_fit_score(10.0, 0.0), 0.0)
        self.assertEqual(sel.time_fit_score(0.0, 0.0), 1.0)
        g = kitchen(timeBudgetMinutes=0.0, timeBudgetWeight=1.0, varietyWeight=0.0)
        recipe(g, "slow", [("input", "Flour", False)], minutes=10.0)
        self.assertEqual(rank(g)["slow"]["score"], 0.0)


class HardExclusionsLookAtWhatIsEaten(unittest.TestCase):
    def setUp(self):
        self.g = kitchen(timeBudgetWeight=1.0, varietyWeight=0.0)
        exclusion(self.g, "no peanuts", "Peanut", "hard")

    def test_a_required_excluded_input_disqualifies(self):
        recipe(self.g, "satay", [("input", "Peanut", False)])
        self.assertTrue(rank(self.g)["satay"]["disqualified"])

    def test_an_optional_excluded_input_does_not_and_says_to_leave_it_out(self):
        recipe(self.g, "salad", [("input", "Flour", False), ("input", "Peanut", True)])
        result = rank(self.g)["salad"]
        self.assertFalse(result["disqualified"])
        self.assertIn("leave out the optional excluded", result["reason"])
        self.assertIn("Peanut", result["reason"])

    def test_an_excluded_instrument_does_not(self):
        recipe(self.g, "whisked", [("input", "Flour", False), ("instrument", "Peanut", False)])
        self.assertFalse(rank(self.g)["whisked"]["disqualified"])

    def test_an_excluded_output_does(self):
        recipe(self.g, "makes peanut butter", [("input", "Flour", False), ("output", "Peanut", False)])
        self.assertTrue(rank(self.g)["makes peanut butter"]["disqualified"])


class SoftExclusionsCost(unittest.TestCase):
    def test_a_soft_exclusion_lowers_the_score_by_its_weight(self):
        g = kitchen(timeBudgetWeight=1.0, varietyWeight=0.0)
        exclusion(g, "prefer no almonds", "Almond", "soft", weight=0.3)
        recipe(g, "plain", [("input", "Flour", False)])
        recipe(g, "nutty", [("input", "Almond", False)])
        r = rank(g)
        self.assertAlmostEqual(r["plain"]["score"], 1.0)
        self.assertAlmostEqual(r["nutty"]["score"], 0.7)
        self.assertFalse(r["nutty"]["disqualified"])
        self.assertIn("prefer no almonds", r["nutty"]["reason"])

    def test_a_soft_exclusion_is_not_a_ban(self):
        g = kitchen(timeBudgetWeight=1.0, varietyWeight=0.0)
        exclusion(g, "prefer no almonds", "Almond", "soft", weight=5.0)
        recipe(g, "nutty", [("input", "Almond", False)])
        self.assertFalse(rank(g)["nutty"]["disqualified"])

    def test_a_score_of_zero_ranks_above_a_negative_one(self):
        g = kitchen(timeBudgetWeight=0.0, varietyWeight=0.0)
        exclusion(g, "prefer no almonds", "Almond", "soft", weight=0.3)
        recipe(g, "penalised", [("input", "Almond", False)])
        recipe(g, "unaffected", [("input", "Flour", False)])
        names = [r["plan"]["name"] for r in sel.select(g, "week", when(25))]
        self.assertEqual(names, ["unaffected", "penalised"])     # `score or -1` put the zero last


if __name__ == "__main__":
    unittest.main()
