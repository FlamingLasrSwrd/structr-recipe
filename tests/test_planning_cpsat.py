"""The CP-SAT adapter against the brute-force oracle.

Skipped when OR-tools is not installed (it is optional; see requirements-solver.txt);
run with the virtualenv's interpreter to exercise it:
    .venv/bin/python -m unittest tests.test_planning_cpsat

CP-SAT models the problem with scaled integers, so the point of these tests is that
its verdicts and scores match evaluate()'s, on the same random problems the exact
search is held to: whether a feasible plan exists, the best score when the model is
exact, and the closest plan when none is feasible.
"""

import unittest
from unittest import mock

from mealplanner.planning import cpsat
from mealplanner.planning.search import SearchResult, auto, oracle, solve
from tests.planning_fixtures import day_of_three, protein_target
from tests.test_planning_search import SEEDS, random_problem

TOL = 1e-4


def stock_is_exact(problem) -> bool:
    """CP-SAT models stock and waste only by their ceiling: when they carry weight and there is stock, its score is an upper bound."""
    return not (problem.lots and problem.weights.stock + problem.weights.waste > 0)


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class WorkedDay(unittest.TestCase):
    def setUp(self):
        self.p = day_of_three([protein_target(70, 140, weight=0.2)])

    def test_it_finds_the_proven_optimum(self):
        r = cpsat.solve(self.p)
        self.assertTrue(r.proven and r.best.feasible)
        self.assertAlmostEqual(r.best.objective, 1.7)                   # three omelettes, worked by hand
        self.assertAlmostEqual(r.upper_bound, 1.7, places=4)
        self.assertEqual([pick.candidate for pick in r.best.picks], ["omelette"] * 3)

    def test_no_feasible_plan_is_a_proof(self):
        r = cpsat.solve(day_of_three([protein_target(140, None)]))
        self.assertTrue(r.proven)
        self.assertIsNone(r.best)

    def test_the_closest_plan_and_its_exact_shortfall(self):
        r = cpsat.solve(day_of_three([protein_target(140, None)]), relaxed=True)
        self.assertEqual([pick.candidate for pick in r.best.picks], ["braised chicken"] * 3)
        self.assertAlmostEqual(r.best.violation_measure, 5 / 140, places=5)
        self.assertTrue(r.proven)

    def test_the_same_problem_gives_the_same_plan(self):
        self.assertEqual(cpsat.solve(self.p).best.picks, cpsat.solve(self.p).best.picks)

    def test_the_facade_uses_it(self):
        self.assertEqual(solve(self.p, "cpsat").method, "cpsat")

    def test_auto_turns_to_it_when_the_short_exact_search_does_not_finish(self):
        unfinished = SearchResult(None, False, 0, "exact")
        with mock.patch("mealplanner.planning.search.exact", return_value=unfinished):
            result = auto(self.p)
        self.assertEqual(result.method, "cpsat")
        self.assertTrue(result.proven)

    def test_auto_labels_the_whole_portfolio_when_nothing_is_proven(self):
        unfinished = SearchResult(None, False, 0, "exact")
        unproven = SearchResult(None, False, 0, "cpsat", upper_bound=2.5)
        with mock.patch("mealplanner.planning.search.exact", return_value=unfinished), \
             mock.patch.object(cpsat, "solve", return_value=unproven):
            result = auto(self.p)
        self.assertEqual((result.method, result.proven, result.upper_bound), ("exact+cpsat+beam", False, 2.5))
        self.assertTrue(result.best.feasible)                # the beam search found the plan


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class AgreesWithTheOracle(unittest.TestCase):
    def test_strict_mode_on_random_problems(self):
        proven = exact_optimum = 0
        for seed in SEEDS:
            p = random_problem(seed)
            want, got = oracle(p), cpsat.solve(p)
            if got.best is None:
                self.assertIsNone(want.best, f"seed {seed}: CP-SAT found nothing but a feasible plan exists")
                self.assertTrue(got.proven, f"seed {seed}: infeasibility must be a proof")
                continue
            self.assertIsNotNone(want.best, f"seed {seed}: CP-SAT returned a plan for an infeasible problem")
            self.assertTrue(got.best.feasible, seed)
            self.assertLessEqual(got.best.objective, want.best.objective + TOL, f"seed {seed}: better than the optimum")
            self.assertGreaterEqual(got.upper_bound, want.best.objective - TOL, f"seed {seed}: the ceiling is below the optimum")
            if got.proven:
                proven += 1
                self.assertAlmostEqual(got.best.objective, want.best.objective, delta=TOL, msg=f"seed {seed}: proven but not optimal")
            if stock_is_exact(p):
                exact_optimum += 1
                self.assertAlmostEqual(got.best.objective, want.best.objective, delta=TOL, msg=f"seed {seed}: exact model, wrong optimum")
        self.assertGreater(proven, 25)             # the proof path is genuinely exercised
        self.assertGreater(exact_optimum, 25)

    def test_relaxed_mode_on_random_problems(self):
        compared = 0
        for seed in SEEDS:
            p = random_problem(seed)
            want, got = oracle(p, relaxed=True), cpsat.solve(p, relaxed=True)
            if want.best is None:
                self.assertIsNone(got.best, seed)
                continue
            self.assertIsNotNone(got.best, f"seed {seed}: no closest plan found")
            compared += 1
            self.assertAlmostEqual(got.best.violation_measure, want.best.violation_measure, delta=1e-5, msg=f"seed {seed}: violation")
            if stock_is_exact(p):
                self.assertAlmostEqual(got.best.objective, want.best.objective, delta=TOL, msg=f"seed {seed}: score among the closest")
        self.assertGreater(compared, 50)


class WithoutOrTools(unittest.TestCase):
    def test_solving_says_how_to_install_it(self):
        with mock.patch.object(cpsat, "available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "requirements-solver.txt"):
                cpsat.solve(day_of_three([protein_target(70, 140, weight=0.2)]))


if __name__ == "__main__":
    unittest.main()
