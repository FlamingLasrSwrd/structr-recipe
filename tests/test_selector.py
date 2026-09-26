"""Selector behaviour through select(), on a minimal in-memory graph: numbers
that are legitimately zero, exclusions by role, soft exclusions, and ordering."""

import importlib.util
import os
import unittest
from datetime import timedelta

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


class VarietyIsDistanceToTheNearestUse(unittest.TestCase):
    """A recipe used (or planned) within the 14-day cap of the slot scores distance / 14, in either direction.
    The old code measured only "days since", so a use planned for next week counted as "just used" (days
    ago went negative and was clamped to 0), and a skipped entry counted as a use."""

    TODAY = when(25)

    def score(self, entries, reference=None):
        """entries: [(days from today, skipped)] for one recipe (negative = in the past)."""
        g = kitchen()
        recipe(g, "stew", [("input", "Flour", False)])
        refs = []
        for i, (offset, skipped) in enumerate(entries):
            start = (self.TODAY + timedelta(days=offset)).strftime("%Y-%m-%dT%H:%M:%S%z")
            g.add("TemporalRegion", f"r{i}", hasBeginning=start)
            g.add("MealPlanEntry", f"e{i}", isAbout=Ref(f"r{i}"), isSkipped=skipped)
            refs.append(Ref(f"e{i}"))
        g.nodes["stew"]["referencedByEntries"] = refs
        return sel.variety_score(g, "stew", reference or self.TODAY)

    def test_never_used_is_the_maximum(self):
        self.assertEqual(self.score([]), 1.0)

    def test_a_week_ago_is_half(self):
        self.assertAlmostEqual(self.score([(-7, False)]), 0.5)

    def test_a_use_planned_for_next_week_counts_the_same_as_last_week(self):
        # was 0.0: 7 days ahead read as -7 days ago and was clamped to zero
        self.assertAlmostEqual(self.score([(7, False)]), 0.5)

    def test_the_nearest_of_several_uses_decides(self):
        # yesterday and ten days ahead: the nearer, 1 day, scores 1/14
        self.assertAlmostEqual(self.score([(-1, False), (10, False)]), 1 / 14)

    def test_beyond_the_cap_is_the_maximum(self):
        self.assertEqual(self.score([(-24, False), (20, False)]), 1.0)

    def test_a_skipped_entry_is_not_a_use(self):
        self.assertEqual(self.score([(-1, True)]), 1.0)          # yesterday, but it never happened

    def test_the_reference_time_is_the_slot_not_today(self):
        # used today; the meal being chosen is three days from now
        self.assertAlmostEqual(self.score([(0, False)], reference=self.TODAY + timedelta(days=3)), 3 / 14)


if __name__ == "__main__":
    unittest.main()
