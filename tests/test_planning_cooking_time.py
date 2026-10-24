"""The week's cooking time as an optional weight (Weights.cooking_time; docs/optimizer-design.md Sec 12):
the owner's decision, 2026-10-24, "an optional preference that can be adjusted week-to-week".

The day of three (tests/planning_fixtures.py) with leftovers kept 3 days: at 0 the time term alone
picks the quickest recipe for every meal; weighed, a cook's minutes count against the week, so the
week cooks less: fewer cooks (leftovers instead) or quicker ones.
"""

import random
import unittest
from dataclasses import replace

from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, options, prefix_bound
from mealplanner.planning.model import Pick, PrepSession, Weights
from mealplanner.planning.search import auto, beam, exact, improve, oracle
from tests.planning_fixtures import cand, day_of_three, when
from tests.test_plan_week_tool import WEEK, read, tool

KEPT = tuple(replace(c, leftover_days=3.0) for c in (
    cand("buttered pasta", 12, 20), cand("veggie stir-fry", 10, 25), cand("omelette", 24, 35), cand("braised chicken", 45, 90),
    cand("mystery stew", 20, None)))


def day(weight, **kw):
    return day_of_three([], KEPT, weights=Weights(time=0.6, variety=0.3, time_budget_minutes=30.0, cooking_time=weight), **kw)


def cooked_minutes(p, ev):
    return sum(p.candidates[x.candidate].minutes or 30.0 for x in ev.picks if x.candidate is not None)


class TheTerm(unittest.TestCase):
    def test_each_cook_costs_its_minutes_and_leftovers_nothing(self):
        p = day(2.0)
        ev = evaluate(p, (Pick(candidate="omelette"), Pick(source=0), Pick(candidate="braised chicken")))
        self.assertAlmostEqual(ev.terms["cooking_time"], -2.0 * (35 + 90) / 60)

    def test_a_recipe_with_no_time_costs_the_meals_budget(self):
        p = day(1.0)
        ev = evaluate(p, (Pick(candidate="mystery stew"), Pick(source=0), Pick(source=0)))
        self.assertAlmostEqual(ev.terms["cooking_time"], -30.0 / 60)

    def test_a_dish_made_at_a_prep_session_is_cooking_too(self):
        session = PrepSession("prep", when(27, 14), 120.0, 2)
        p = day(1.0, preps=(session,), now=when(26, 9))
        ev = evaluate(p, (Pick(candidate="omelette", prep=0), Pick(source=0), Pick(source=0)))
        self.assertAlmostEqual(ev.terms["cooking_time"], -35.0 / 60)

    def test_at_zero_it_is_not_there(self):
        ev = evaluate(day(0.0), (Pick(candidate="omelette"),) * 3)
        self.assertNotIn("cooking_time", ev.terms)


class TheBestWeek(unittest.TestCase):
    def test_weighed_the_week_cooks_less_and_every_search_agrees(self):
        light, heavy = oracle(day(0.0)).best, oracle(day(4.0)).best
        self.assertLess(cooked_minutes(day(4.0), heavy), cooked_minutes(day(0.0), light))
        p = day(4.0)
        for result in (exact(p), beam(p), auto(p, time_limit_s=2), improve(p, evaluate(p, light.picks))):
            self.assertAlmostEqual(result.best.objective, heavy.objective, msg=result.method)

    def test_the_bound_never_falls_below_what_a_week_comes_to(self):
        rng = random.Random(5)
        p = day(3.0)
        for _ in range(150):
            partial = [None] * 3
            for i in range(3):
                partial[i] = rng.choice(options(p, partial, i))
            final = evaluate(p, partial).objective
            for k in range(4):
                self.assertGreaterEqual(prefix_bound(p, partial[:k] + [None] * (3 - k)).objective, final - 1e-9)

    def test_a_negative_weight_is_refused(self):
        with self.assertRaises(ValueError):
            day(-1.0)


class TheWeekFile(unittest.TestCase):
    def test_read_from_the_weights_and_checked(self):
        self.assertEqual(read(WEEK + "[weights]\ncooking_time = 1.5\n")["weights"]["cooking_time"], 1.5)
        for bad in ("-1", '"lots"', "true"):
            with self.assertRaises(tool.WeekError) as caught:
                read(WEEK + f"[weights]\ncooking_time = {bad}\n")
            self.assertIn("cooking_time is points an hour", " ".join(caught.exception.args[0]))


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_cpsat_weighs_the_weeks_cooking_as_the_oracle_does(self):
        for weight in (0.5, 2.0, 4.0):
            p = day(weight)
            self.assertAlmostEqual(cpsat.solve(p).best.objective, oracle(p).best.objective, msg=weight)


if __name__ == "__main__":
    unittest.main()
