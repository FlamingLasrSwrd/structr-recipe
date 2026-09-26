"""The searches against the oracle, and the bounds they rely on.

The oracle enumerates every legal assignment and scores each with evaluate(), so
its answer needs no trust in the pruning. On randomly generated small problems
(fixed seeds, so failures reproduce) the exact search must find the same optimum,
the same infeasibility verdict, and the same closest plan; and prefix_bound must
never promise less than a completion delivers.
"""

import random
import unittest
from unittest import mock

from mealplanner.planning.evaluate import evaluate, initial_partial, prefix_bound
from mealplanner.planning.model import Fixed, Lot, Pick, Weights
from mealplanner.planning.search import auto, beam, enumerate_assignments, exact, oracle, solve
from tests.planning_fixtures import MEALS, cand, day_of_three, problem, protein_target, slot, when

TOL = 1e-7
SEEDS = range(80)


def random_problem(seed: int):
    rnd = random.Random(seed)
    candidates = []
    for i in range(rnd.randint(2, 4)):
        candidates.append(cand(
            f"r{i}", rnd.choice([None, 5, 12, 24, 30, 45, 60]), rnd.choice([None, 10, 25, 40, 90]),
            yield_servings=rnd.choice([1.0, 2.0, 4.0]),
            leftover_days=rnd.choice([None, None, 2.0, 5.0]),
            meal_types=frozenset(rnd.sample(["A", "B"], rnd.randint(1, 2))),
            soft_penalty=rnd.choice([0.0, 0.0, 0.2]),
            hard_excluded=rnd.random() < 0.08,
            untrusted=frozenset({"protein"}) if rnd.random() < 0.1 else frozenset(),
            demand={"p": rnd.choice([100.0, 200.0, 400.0])} if rnd.random() < 0.7 else {},
            uses=tuple(when(rnd.randint(20, 26), 18) for _ in range(rnd.randint(0, 1))),
        ))
    starts = sorted(when(rnd.randint(27, 30), rnd.choice([8, 12, 18])) for _ in range(rnd.randint(2, 4)))
    slots = [slot(f"s{i}", start, rnd.choice([None, "A", "B"])) for i, start in enumerate(starts)]
    if rnd.random() < 0.3:
        slots[0] = slot("s0", starts[0], None, Fixed(eaten=1.0, candidate=candidates[0].id))
    targets = []
    for _ in range(rnd.randint(0, 2)):
        targets.append(protein_target(
            rnd.choice([None, 30, 60]), rnd.choice([None, 80, 150]), hard=rnd.random() < 0.6,
            scope=rnd.choice(["per_meal", "daily", "weekly"]), weight=rnd.choice([0.0, 0.3, 0.6]),
        ))
    lots = [Lot("p", rnd.choice([50.0, 150.0, 400.0]), when(rnd.randint(27, 33), 12)) for _ in range(rnd.randint(0, 2))]
    weights = Weights(*(round(rnd.random(), 2) for _ in range(4)), time_budget_minutes=30.0)
    return problem(slots, candidates, targets, lots, weights=weights,
                   max_difficulty=None)


class ExactAgreesWithTheOracle(unittest.TestCase):
    def test_strict_mode(self):
        for seed in SEEDS:
            p = random_problem(seed)
            want, got = oracle(p), exact(p)
            self.assertTrue(got.proven, seed)
            self.assertEqual(want.best is None, got.best is None, f"seed {seed}: feasibility verdict")
            if want.best:
                self.assertAlmostEqual(want.best.objective, got.best.objective, delta=TOL, msg=f"seed {seed}")
                self.assertTrue(got.best.feasible, seed)

    def test_relaxed_mode_finds_the_same_closest_plan(self):
        for seed in SEEDS:
            p = random_problem(seed)
            want, got = oracle(p, relaxed=True), exact(p, relaxed=True)
            self.assertEqual(want.best is None, got.best is None, f"seed {seed}")
            if want.best:
                self.assertAlmostEqual(want.best.violation_measure, got.best.violation_measure, delta=TOL, msg=f"seed {seed}")
                self.assertAlmostEqual(want.best.objective, got.best.objective, delta=TOL, msg=f"seed {seed}")

    def test_the_pruning_actually_prunes(self):
        # on the worked day the exact search must look at far fewer nodes than the 125 + 25 + 5 of full enumeration
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        self.assertLess(exact(p).nodes, oracle(p).total_count)


class BeamIsValidButNotOptimal(unittest.TestCase):
    def test_whatever_beam_returns_is_feasible_and_no_better_than_the_optimum(self):
        found = 0
        for seed in SEEDS:
            p = random_problem(seed)
            want, got = oracle(p), beam(p, width=6)
            self.assertFalse(got.proven)
            if got.best is not None:
                found += 1
                self.assertTrue(got.best.feasible, seed)
                self.assertLessEqual(got.best.objective, want.best.objective + TOL, seed)
        self.assertGreater(found, 20)                      # it finds something on most of them

    def test_a_wide_enough_beam_finds_the_optimum_here(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        self.assertAlmostEqual(beam(p, width=200).best.objective, oracle(p).best.objective)


class TheBoundsAreSound(unittest.TestCase):
    def test_no_prefix_promises_less_than_its_completions_deliver(self):
        checked = 0
        for seed in SEEDS:
            p = random_problem(seed)
            open_slots = p.open_slots()
            for picks in enumerate_assignments(p):
                if random.Random(repr((seed, picks))).random() > 0.15:
                    continue                             # a sample of the assignments
                ev = evaluate(p, picks)
                partial = initial_partial(p)
                for k in range(len(open_slots) + 1):
                    b = prefix_bound(p, partial)
                    self.assertGreaterEqual(b.objective, ev.objective - TOL, f"seed {seed}, prefix {k}, objective")
                    self.assertLessEqual(b.violation, ev.violation_measure + TOL, f"seed {seed}, prefix {k}, violation")
                    checked += 1
                    if k < len(open_slots):
                        partial[open_slots[k]] = picks[open_slots[k]]
        self.assertGreater(checked, 1000)

    def test_a_complete_assignment_bound_is_its_own_score_when_stock_is_not_weighed(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        picks = (Pick(candidate="omelette"),) * 3
        self.assertAlmostEqual(prefix_bound(p, list(picks)).objective, evaluate(p, picks).objective)


class Facade(unittest.TestCase):
    def test_solve_dispatches(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        self.assertEqual({solve(p, m).method for m in ("exact", "beam", "oracle")}, {"exact", "beam", "oracle"})
        with self.assertRaises(ValueError):
            solve(p, "magic")

    def test_a_node_limit_returns_the_best_so_far_marked_unproven(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        result = exact(p, node_limit=12)
        self.assertFalse(result.proven)

    def test_a_problem_with_nothing_to_decide_is_just_evaluated(self):
        p = problem([slot("only", when(28, 18), fixed=Fixed(eaten=1.0, candidate="omelette"))], MEALS, [protein_target(20, None)])
        result = exact(p)
        self.assertTrue(result.proven and result.best.feasible)


class Auto(unittest.TestCase):
    """auto() behaves the same in outline with or without OR-tools; these pin the parts that do not depend on it."""

    def test_a_small_week_is_proven_optimal(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        result = auto(p)
        self.assertTrue(result.proven)
        self.assertEqual(result.method, "exact")             # the short exact search proves a week this small
        self.assertAlmostEqual(result.best.objective, oracle(p).best.objective)

    def test_without_ortools_it_falls_back_and_says_it_is_not_proven(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        with mock.patch("mealplanner.planning.cpsat.available", return_value=False):
            result = auto(p, node_limit=5)
        self.assertFalse(result.proven)
        self.assertEqual(result.method, "exact+beam")
        self.assertTrue(result.best is not None and result.best.feasible)
        self.assertIsNone(result.upper_bound)

    def test_the_default_method_is_auto(self):
        p = day_of_three([protein_target(70, 140, weight=0.2)])
        self.assertEqual(solve(p).method, "exact")
        self.assertTrue(solve(p).proven)

    def test_an_infeasible_problem_is_still_proven_infeasible(self):
        p = day_of_three([protein_target(140, None)])
        result = auto(p)
        self.assertTrue(result.proven and result.best is None)


if __name__ == "__main__":
    unittest.main()
