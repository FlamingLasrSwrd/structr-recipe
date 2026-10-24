"""The week's repeat tolerance (PlanningProblem.repeat_tolerance; docs/optimizer-design.md Sec 12):
the owner's request, 2026-10-24, "How often would you tolerate eating the same meal in a week?".

The day of three (tests/planning_fixtures.py) with leftovers kept 3 days. A recipe may be eaten at
no more than the tolerance's meals of the week, fresh, as leftovers or made at a prep session; a
recipe's versions are one recipe; meals already committed count, and the planner adds none to a
recipe they already take past it.
"""

import unittest
from dataclasses import replace

from mealplanner.planning import cpsat
from mealplanner.planning.diagnose import diagnose
from mealplanner.planning.evaluate import evaluate, meals_of, options, resolve
from mealplanner.planning.model import Fixed, Pick, PrepSession, Weights
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import auto, beam, enumerate_assignments, exact, improve, oracle
from tests.planning_fixtures import cand, day_of_three, problem, slot, when
from tests.test_planning_cpsat import stock_is_exact
from tests.test_planning_search import SEEDS, TOL, random_problem
from tests.test_plan_week_tool import WEEK, read, tool

KEPT = tuple(replace(c, leftover_days=3.0) for c in (
    cand("buttered pasta", 12, 20), cand("veggie stir-fry", 10, 25), cand("omelette", 24, 35)))
WEIGHTS = Weights(time=0.6, variety=0.3, time_budget_minutes=30.0, cooking_time=3.0)    # leftovers pay: pasta, eaten 3 times


def day(tolerance, candidates=KEPT, **kw):
    return day_of_three([], candidates, weights=WEIGHTS, repeat_tolerance=tolerance, **kw)


def most_meals(p, ev) -> int:
    fixed, open_ = meals_of(p, resolve(p, list(ev.picks))[0])
    return max(fixed.get(k, 0) + open_.get(k, 0) for k in set(fixed) | set(open_))


class Options(unittest.TestCase):
    def test_a_recipe_at_its_tolerance_is_not_offered_again(self):
        once = [Pick(candidate="omelette"), None, None]
        self.assertFalse([o for o in options(day(1), once, 1) if o.candidate == "omelette" or o.source == 0])
        twice = options(day(2), once, 1)
        self.assertIn(Pick(source=0), twice)
        self.assertNotIn(Pick(candidate="omelette"), options(day(2), [Pick(candidate="omelette"), Pick(source=0), None], 2))
        self.assertNotIn(Pick(source=0), options(day(2), [Pick(candidate="omelette"), Pick(source=0), None], 2))

    def test_without_one_nothing_changes(self):
        once = [Pick(candidate="omelette"), None, None]
        self.assertEqual(options(day(None), once, 1), options(day(3), once, 1))


class Evaluated(unittest.TestCase):
    def test_more_meals_than_tolerated_is_not_a_week(self):
        ev = evaluate(day(1), (Pick(candidate="omelette"), Pick(source=0), Pick(candidate="buttered pasta")))
        self.assertFalse(ev.legal)
        self.assertEqual(ev.problems, ["omelette: 2 meals this week, more than the 1 tolerated"])
        self.assertTrue(evaluate(day(2), ev.picks).legal)

    def test_a_recipes_versions_are_one_recipe(self):
        versions = (replace(KEPT[2], id="omelette v1", recipe="omelette"), replace(KEPT[2], id="omelette v2", recipe="omelette"),
                    KEPT[0])
        ev = evaluate(day(1, versions), (Pick(candidate="omelette v1"), Pick(candidate="omelette v2"), Pick(candidate="buttered pasta")))
        self.assertEqual(ev.problems, ["omelette: 2 meals this week, more than the 1 tolerated"])

    def test_committed_meals_count_and_stand(self):
        breakfast = Fixed(candidate="omelette", cooked=2.0, name="omelette, committed")
        slots = [slot("breakfast", when(28, 8), fixed=breakfast), slot("lunch", when(28, 12)), slot("dinner", when(28, 18))]
        p = problem(slots, KEPT, weights=WEIGHTS, repeat_tolerance=1)
        self.assertFalse(evaluate(p, (Pick(candidate="omelette"), Pick(source=0), Pick(candidate="buttered pasta"))).legal)
        best = oracle(p).best
        self.assertEqual(most_meals(p, best), 1)
        self.assertNotIn("omelette", [x.candidate for x in best.picks[1:]])

    def test_a_dish_made_at_a_prep_session_is_one_meal_and_its_leftovers_more(self):
        session = PrepSession("prep", when(27, 14), 120.0, 2)
        p = day(1, preps=(session,), now=when(26, 9))
        self.assertTrue(evaluate(p, (Pick(candidate="omelette", prep=0), Pick(candidate="veggie stir-fry"), Pick(candidate="buttered pasta"))).legal)
        self.assertFalse(evaluate(p, (Pick(candidate="omelette", prep=0), Pick(source=0), Pick(candidate="buttered pasta"))).legal)


class TheBestWeek(unittest.TestCase):
    def test_every_search_keeps_to_it_and_agrees(self):
        free = oracle(day(None)).best
        self.assertEqual(most_meals(day(None), free), 3)            # weighed cooking: one cook, eaten three times
        for tolerance in (1, 2, 3):
            p = day(tolerance)
            best = oracle(p).best
            self.assertLessEqual(most_meals(p, best), tolerance)
            for result in (exact(p), beam(p), auto(p, time_limit_s=2), improve(p, evaluate(p, best.picks))):
                self.assertAlmostEqual(result.best.objective, best.objective, msg=(tolerance, result.method))
                self.assertLessEqual(most_meals(p, result.best), tolerance, msg=(tolerance, result.method))
        self.assertFalse([x for x in oracle(day(1)).best.picks if x.source is not None])     # 1: no leftovers at all

    def test_the_report_says_the_most(self):
        p = day(2)
        text = describe_plan(p, oracle(p).best)
        self.assertIn("repeats: at most 2 meal(s) of one recipe this week; the most, 2:", text)


def limited(seed: int):
    return replace(random_problem(seed), repeat_tolerance=1 + seed % 2, _cache={})


class RandomWeeks(unittest.TestCase):
    """tests/test_planning_search.py's random problems, at a tolerance of 1 or 2."""

    def test_the_options_leave_out_exactly_the_weeks_over_it(self):
        for seed in SEEDS[:40]:
            p, free = limited(seed), random_problem(seed)
            legal = [a for a in enumerate_assignments(free) if evaluate(p, a).legal]
            self.assertEqual(list(enumerate_assignments(p)), legal, seed)

    def test_the_exact_search_agrees_with_the_oracle(self):
        bound = 0
        for seed in SEEDS:
            p = limited(seed)
            for relaxed in (False, True):
                want, got = oracle(p, relaxed=relaxed), exact(p, relaxed=relaxed)
                self.assertEqual(want.best is None, got.best is None, (seed, relaxed))
                if want.best:
                    self.assertAlmostEqual(want.best.objective, got.best.objective, delta=TOL, msg=(seed, relaxed))
                    self.assertLessEqual(most_meals(p, got.best), p.repeat_tolerance)
            bound += oracle(random_problem(seed)).best is not None and oracle(p).best is None
        self.assertGreater(bound, 0)               # the limit genuinely leaves some weeks with no plan


class TooFew(unittest.TestCase):
    def test_a_week_short_of_recipes_says_so(self):
        dinners = tuple(replace(c, meal_types=frozenset({"Dinner"})) for c in KEPT[:1])
        slots = [slot(f"d{d}", when(d, 18), "Dinner") for d in (27, 28, 29)]
        p = problem(slots, dinners, weights=WEIGHTS, repeat_tolerance=2)
        self.assertIsNone(oracle(p).best)
        self.assertIn("3 Dinner meals, but the 1 recipe(s) for them may fill only 2 at 2 meal(s) each (repeat_tolerance)",
                      " ".join(diagnose(p, time_limit_s=2).impossible_alone))

    def test_it_is_a_whole_number_of_meals(self):
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                day(bad)


class TheWeekFile(unittest.TestCase):
    def test_read_and_checked(self):
        self.assertEqual(read(WEEK + "repeat_tolerance = 2\n")["repeat_tolerance"], 2)
        self.assertIsNone(read(WEEK).get("repeat_tolerance"))
        for bad in ("0", "1.5", '"twice"', "true"):
            with self.assertRaises(tool.WeekError) as caught:
                read(WEEK + f"repeat_tolerance = {bad}\n")
            self.assertIn("repeat_tolerance is the most meals of the week one recipe may be", " ".join(caught.exception.args[0]))

    def test_a_recipe_asked_for_more_often_than_tolerated(self):
        with self.assertRaises(tool.WeekError) as caught:
            read(WEEK + 'repeat_tolerance = 1\ncook = ["Omelette", "Omelette"]\n')
        self.assertIn("cook: Omelette is asked for 2 times, more than the repeat_tolerance of 1", caught.exception.args[0])


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_cpsat_keeps_to_it_as_the_oracle_does(self):
        for tolerance in (1, 2, 3):
            p = day(tolerance)
            result = cpsat.solve(p)
            self.assertAlmostEqual(result.best.objective, oracle(p).best.objective, msg=tolerance)
            self.assertLessEqual(most_meals(p, result.best), tolerance)

    def test_cpsat_agrees_on_random_weeks(self):
        for seed in SEEDS:
            p = limited(seed)
            want, got = oracle(p), cpsat.solve(p)
            self.assertEqual(want.best is None, got.best is None, seed)
            if want.best and stock_is_exact(p):
                self.assertAlmostEqual(got.best.objective, want.best.objective, delta=TOL, msg=seed)

    def test_committed_meals_count_in_cpsat_too(self):
        breakfast = Fixed(candidate="omelette", cooked=2.0, name="omelette, committed")
        slots = [slot("breakfast", when(28, 8), fixed=breakfast), slot("lunch", when(28, 12)), slot("dinner", when(28, 18))]
        p = problem(slots, KEPT, weights=WEIGHTS, repeat_tolerance=1)
        self.assertAlmostEqual(cpsat.solve(p).best.objective, oracle(p).best.objective)


if __name__ == "__main__":
    unittest.main()
