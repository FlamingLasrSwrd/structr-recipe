"""The nutrient report (mealplanner/planning/nutrients.py), worked by hand.

One day, lunch and dinner, from three recipes (protein per serving): lean 10 g, mid 30 g, rich 50 g.
The most a day can hold is 100 g, the least 20 g. With a baseline of 15 g a day those are 115 and 35.
"""

import unittest

from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.model import Pick
from mealplanner.planning.nutrients import describe_nutrients, num, richest, standings
from tests.planning_fixtures import cand, problem, protein_target, slot, when

RECIPES = (cand("lean", 10, 20), cand("mid", 30, 20), cand("rich", 50, 20))


def day(target, baseline=None, recipes=RECIPES):
    return problem([slot("lunch", when(28, 12)), slot("dinner", when(28, 18))], recipes, [target],
                   baseline=baseline or {}, units={"protein": "g"})


def standing(target, picks, **kw):
    p = day(target, **kw)
    (s,) = standings(p, evaluate(p, tuple(Pick(candidate=c) for c in picks)))
    return s


class Standings(unittest.TestCase):
    def test_met_missed_and_impossible(self):
        self.assertEqual(standing(protein_target(50, None, hard=False, weight=0.1), ("mid", "mid")).met, 1)
        self.assertEqual(standing(protein_target(50, None, hard=False, weight=0.1), ("lean", "lean")).missed, 1)
        s = standing(protein_target(120, None, hard=False, weight=0.1), ("rich", "rich"))       # 100 at most
        self.assertEqual((s.impossible, s.reach), (1, [(20.0, 100.0)]))
        s = standing(protein_target(None, 15, hard=False, weight=0.1), ("lean", "lean"))       # 20 at least
        self.assertEqual(s.impossible, 1)

    def test_the_baseline_moves_what_is_possible(self):
        s = standing(protein_target(110, None, hard=False, weight=0.1), ("rich", "rich"), baseline={"protein": 15.0})
        self.assertEqual(s.met, 1)                                                              # 100 + 15
        s = standing(protein_target(None, 30, hard=False, weight=0.1), ("lean", "lean"), baseline={"protein": 15.0})
        self.assertEqual((s.impossible, s.reach), (1, [(35.0, 115.0)]))

    def test_a_recipe_with_no_figure_rules_out_impossible(self):
        recipes = RECIPES + (cand("mystery", None, 20),)
        s = standing(protein_target(120, None, hard=False, weight=0.1), ("rich", "rich"), recipes=recipes)
        self.assertEqual((s.impossible, s.missed), (0, 1))                                      # mystery might have plenty
        s = standing(protein_target(120, None, hard=False, weight=0.1), ("mystery", "rich"), recipes=recipes)
        self.assertEqual(s.unknown, 1)


class Words(unittest.TestCase):
    def test_the_report_names_the_problem_and_where_to_look(self):
        p = day(protein_target(120, None, hard=False, weight=0.1))
        text = describe_nutrients(p, evaluate(p, (Pick(candidate="rich"),) * 2))
        self.assertIn("impossible on 1, where the recipes can reach at most 100 g", text)
        self.assertIn("richest per serving: rich 50 g, mid 30 g, lean 10 g", text)

    def test_leanest_when_over_a_maximum(self):
        p = day(protein_target(None, 50, hard=False, weight=0.1))
        text = describe_nutrients(p, evaluate(p, (Pick(candidate="rich"),) * 2))
        self.assertIn("leanest per serving: lean 10 g", text)

    def test_figures_read_as_written(self):
        self.assertEqual([num(x) for x in (1890.4, 35.0, 7.128, 0.8679)], ["1,890", "35", "7.13", "0.87"])
        self.assertEqual(richest(day(protein_target(1, None)), "protein", lowest=True, n=1), [("lean", 10)])


if __name__ == "__main__":
    unittest.main()
