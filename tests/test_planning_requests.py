"""Recipes the owner asks for (planning/model.Request; docs/optimizer-design.md Sec 12).

The day of three (tests/planning_fixtures.py) with no targets and only the time term weighted:
left alone, every search fills it with the quickest recipe, so braised chicken (90 minutes, the
slowest) is what a request has to bring in.
"""

import random
import unittest

from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, prefix_bound
from mealplanner.planning.model import Fixed, Pick, Request
from mealplanner.planning.search import auto, beam, exact, improve, oracle
from tests.planning_fixtures import MEALS, day_of_three, problem, slot, when

BRAISE = frozenset({"braised chicken"})


def asked(*pins, count=1, **kw):
    requests = [Request("braised chicken", BRAISE, pin) for pin in pins] + [Request("braised chicken", BRAISE)] * count
    return day_of_three([], requests=tuple(requests), **kw)


def braises(ev):
    return [i for i, pick in enumerate(ev.picks) if pick.candidate == "braised chicken"]


class Asked(unittest.TestCase):
    def test_left_alone_no_week_has_it_and_asked_for_every_search_cooks_it_once(self):
        self.assertEqual(braises(oracle(day_of_three([])).best), [])
        p = asked()
        best = oracle(p).best
        self.assertEqual(len(braises(best)), 1)
        for result in (exact(p), beam(p), auto(p, time_limit_s=2)):
            self.assertTrue(result.best.feasible, result.method)
            self.assertAlmostEqual(result.best.objective, best.objective, msg=result.method)

    def test_asked_for_twice_is_cooked_twice(self):
        self.assertEqual(len(braises(oracle(asked(count=2)).best)), 2)

    def test_pinned_to_a_meal_it_is_cooked_there(self):
        p = asked(1, count=0)
        self.assertEqual(braises(oracle(p).best), [1])
        self.assertEqual(braises(exact(p).best), [1])

    def test_a_pin_and_a_request_are_two_cooks(self):
        self.assertEqual(braises(oracle(asked(0, count=1)).best)[0], 0)
        self.assertEqual(len(braises(oracle(asked(0, count=1)).best)), 2)

    def test_more_than_the_week_holds_is_not_feasible_and_relaxed_says_by_how_much(self):
        p = asked(count=4)
        self.assertIsNone(oracle(p).best)
        closest = oracle(p, relaxed=True).best
        (v,) = closest.violations
        self.assertEqual((v.kind, v.total, v.bound, v.measure), ("not_cooked", 3, 4, 1.0))

    def test_a_committed_meal_that_cooks_it_answers_the_request(self):
        p = problem([slot("breakfast", when(28, 8), fixed=Fixed(candidate="braised chicken", cooked=1.0)),
                     slot("lunch", when(28, 12)), slot("dinner", when(28, 18))], MEALS,
                    requests=(Request("braised chicken", BRAISE),))
        self.assertEqual(braises(oracle(p).best), [0])

    def test_a_pinned_meal_cooking_something_else_is_not_a_legal_week(self):
        p = asked(1, count=0)
        ev = evaluate(p, (Pick(candidate="omelette"),) * 3)
        self.assertFalse(ev.legal)
        self.assertIn("braised chicken was asked for here", ev.problems[0])

    def test_the_climb_keeps_what_was_asked_for(self):
        p = asked()
        start = exact(p).best
        self.assertEqual(len(braises(improve(p, start).best)), 1)

    def test_the_bound_never_exceeds_what_the_week_comes_to(self):
        rng = random.Random(7)
        p = asked(count=2)
        names = [c.id for c in MEALS]
        for _ in range(200):
            picks = [Pick(candidate=rng.choice(names)) for _ in range(3)]
            final = evaluate(p, picks).violation_measure
            for k in range(4):
                partial = picks[:k] + [None] * (3 - k)
                self.assertLessEqual(prefix_bound(p, partial).violation, final + 1e-9)

    def test_what_cannot_be_asked(self):
        with self.assertRaises(ValueError):
            day_of_three([], requests=(Request("stew", frozenset({"stew"})),))
        with self.assertRaises(ValueError):
            problem([slot("breakfast", when(28, 8), fixed=Fixed(candidate="omelette", cooked=1.0)),
                     slot("dinner", when(28, 18))], MEALS, requests=(Request("braised chicken", BRAISE, 0),))
        with self.assertRaises(ValueError):
            day_of_three([], requests=(Request("braised chicken", BRAISE, 1), Request("omelette", frozenset({"omelette"}), 1)))


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_cpsat_cooks_what_was_asked_for_and_agrees_with_the_oracle(self):
        for p in (asked(), asked(count=2), asked(1, count=0), asked(0, count=1)):
            result = cpsat.solve(p)
            self.assertEqual(len(braises(result.best)), len(braises(oracle(p).best)))
            self.assertAlmostEqual(result.best.objective, oracle(p).best.objective)
            for i, request in p.pinned().items():
                self.assertIn(result.best.picks[i].candidate, request.candidates)

    def test_relaxed_cpsat_measures_a_request_left_out(self):
        p = asked(count=4)
        self.assertIsNone(cpsat.solve(p).best)
        self.assertAlmostEqual(cpsat.solve(p, relaxed=True).best.violation_measure, 1.0)


if __name__ == "__main__":
    unittest.main()
