"""What the planner says when the hard constraints cannot all be met."""

import unittest

from mealplanner.planning.diagnose import diagnose
from mealplanner.planning.model import Fixed
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import exact
from tests.planning_fixtures import MEALS, cand, day_of_three, problem, protein_target, slot, when


class WhenAPlanExists(unittest.TestCase):
    def test_it_says_so(self):
        d = diagnose(day_of_three([protein_target(70, 140, weight=0.2)]))
        self.assertTrue(d.feasible and d.proven)
        self.assertEqual(d.summary(), "A plan meeting every hard constraint exists.")


class WhenNoneDoes(unittest.TestCase):
    def setUp(self):
        # three slots at 45 g at most: 135 g against a minimum of 140 g
        self.p = day_of_three([protein_target(140, None)])
        self.d = diagnose(self.p)

    def test_the_verdict_is_proven(self):
        self.assertFalse(self.d.feasible)
        self.assertTrue(self.d.proven)

    def test_the_closest_plan_and_its_exact_shortfall(self):
        self.assertEqual([pick.candidate for pick in self.d.closest.picks], ["braised chicken"] * 3)
        (v,) = self.d.violations
        self.assertEqual((v.kind, v.total, v.bound), ("below_min", 135, 140))

    def test_the_constraint_is_named_as_impossible_on_its_own(self):
        (text,) = self.d.impossible_alone
        self.assertIn("reaches 135 against a minimum of 140", text)

    def test_the_remedies_rank_recipes_by_what_they_add(self):
        (text,) = self.d.remedies
        self.assertEqual(text, "more Protein per serving: braised chicken (45 per serving), chicken salad (30 per serving), omelette (24 per serving)")

    def test_the_summary_reads_as_a_report(self):
        summary = self.d.summary()
        self.assertIn("No plan meets every hard constraint.", summary)
        self.assertIn("protein target on 2026-09-28: 135 against a minimum of 140 (5 short)", summary)


class DataThatBlocksARecipe(unittest.TestCase):
    def test_a_placeholder_figure_is_reported_as_what_would_close_the_gap(self):
        bar = cand("protein bar", 80, 5, untrusted=frozenset({"protein"}))
        d = diagnose(day_of_three([protein_target(140, None)], candidates=MEALS + (bar,)))
        self.assertIn("protein bar", d.unusable_recipes)
        self.assertTrue(any("protein bar would give 80 per serving but cannot be used" in r for r in d.remedies))
        self.assertIn("left out: protein bar", d.summary())

    def test_a_recipe_left_out_is_reported_even_when_a_plan_exists(self):
        mystery = cand("mystery", None, 5)
        d = diagnose(day_of_three([protein_target(70, None)], candidates=MEALS + (mystery,)))
        self.assertTrue(d.feasible)
        self.assertIn("mystery", d.unusable_recipes)


class FixedEntriesThatBreakAConstraint(unittest.TestCase):
    def test_it_is_pinned_on_the_fixed_entries_not_the_planner(self):
        p = problem([slot("lunch", when(28, 12), fixed=Fixed(eaten=2.0, candidate="braised chicken")), slot("dinner", when(28, 18))],
                    MEALS, [protein_target(None, 60)])                    # 2 servings of 45 g = 90 g, over 60 g
        d = diagnose(p)
        self.assertFalse(d.feasible)
        self.assertTrue(any("already fixed" in text and "exceed the maximum of 60" in text for text in d.impossible_alone))


class Describing(unittest.TestCase):
    def test_a_plan_reads_slot_by_slot(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        text = describe_plan(p, exact(p).best)
        self.assertIn("cook omelette for 1 serving", text)
        self.assertIn("score 1.700", text)


if __name__ == "__main__":
    unittest.main()
