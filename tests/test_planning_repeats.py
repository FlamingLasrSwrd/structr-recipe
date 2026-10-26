"""The week's repeat tolerance (PlanningProblem.repeat_tolerance, Weights.repeats; docs/optimizer-design.md
Sec 12): the owner's request, 2026-10-24, "How often would you tolerate eating the same meal in a week?",
and their decision, 2026-10-26, that it is a soft preference.

The day of three (tests/planning_fixtures.py) with leftovers kept 3 days and the week's cooking weighed
heavily, so that leftovers pay: left alone, the best day cooks buttered pasta once and eats it three
times. Each meal of a recipe beyond the tolerance, fresh, as leftovers or made at a prep session, costs
Weights.repeats; a recipe's versions are one recipe, and committed meals count.
"""

import random
import unittest
from dataclasses import replace

from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, meals_of, options, prefix_bound, resolve
from mealplanner.planning.model import Fixed, Pick, PrepSession, Weights
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import auto, beam, exact, improve, oracle
from tests.planning_fixtures import cand, day_of_three, problem, slot, when
from tests.test_planning_cpsat import stock_is_exact
from tests.test_planning_search import SEEDS, TOL, random_problem
from tests.test_plan_week_tool import WEEK, read, tool

CEILING_TOL = 1e-5      # CP-SAT's ceiling is whole millionths of a point (cpsat.OS), each term rounded

KEPT = tuple(replace(c, leftover_days=3.0) for c in (
    cand("buttered pasta", 12, 20), cand("veggie stir-fry", 10, 25), cand("omelette", 24, 35)))
WEIGHTS = Weights(time=0.6, variety=0.3, time_budget_minutes=30.0, cooking_time=3.0)    # leftovers pay: pasta, eaten 3 times


def day(tolerance, repeats=1.0, candidates=KEPT, **kw):
    return day_of_three([], candidates, weights=replace(WEIGHTS, repeats=repeats), repeat_tolerance=tolerance, **kw)


def most_meals(p, ev) -> int:
    fixed, open_ = meals_of(p, resolve(p, list(ev.picks))[0])
    return max(fixed.get(k, 0) + open_.get(k, 0) for k in set(fixed) | set(open_))


class TheTerm(unittest.TestCase):
    def test_each_meal_over_costs_the_weight_and_the_week_stays_legal(self):
        picks = (Pick(candidate="omelette"), Pick(source=0), Pick(source=0))
        ev = evaluate(day(1, repeats=2.0), picks)
        self.assertTrue(ev.legal)
        self.assertAlmostEqual(ev.terms["repeats"], -2.0 * 2)                     # three omelettes, two over one
        self.assertAlmostEqual(evaluate(day(2), picks).terms["repeats"], -1.0)
        self.assertEqual(evaluate(day(3), picks).terms["repeats"], 0)

    def test_nothing_counted_without_a_tolerance_or_a_weight(self):
        picks = (Pick(candidate="omelette"), Pick(source=0), Pick(source=0))
        self.assertNotIn("repeats", evaluate(day(None), picks).terms)
        self.assertNotIn("repeats", evaluate(day(1, repeats=0.0), picks).terms)

    def test_a_recipes_versions_are_one_recipe(self):
        versions = (replace(KEPT[2], id="omelette v1", recipe="omelette"), replace(KEPT[2], id="omelette v2", recipe="omelette"),
                    KEPT[0])
        ev = evaluate(day(1, candidates=versions), (Pick(candidate="omelette v1"), Pick(candidate="omelette v2"), Pick(candidate="buttered pasta")))
        self.assertAlmostEqual(ev.terms["repeats"], -1.0)

    def test_committed_meals_count(self):
        breakfast = Fixed(candidate="omelette", cooked=2.0, name="omelette, committed")
        slots = [slot("breakfast", when(28, 8), fixed=breakfast), slot("lunch", when(28, 12)), slot("dinner", when(28, 18))]
        p = problem(slots, KEPT, weights=WEIGHTS, repeat_tolerance=1)
        ev = evaluate(p, (Pick(candidate="omelette"), Pick(source=0), Pick(candidate="buttered pasta")))
        self.assertAlmostEqual(ev.terms["repeats"], -1.0)                         # the committed omelette and its leftovers

    def test_a_dish_made_at_a_prep_session_is_one_meal_and_its_leftovers_more(self):
        session = PrepSession("prep", when(27, 14), 120.0, 2)
        p = day(1, preps=(session,), now=when(26, 9))
        made = evaluate(p, (Pick(candidate="omelette", prep=0), Pick(source=0), Pick(candidate="buttered pasta")))
        self.assertAlmostEqual(made.terms["repeats"], -1.0)

    def test_the_options_are_every_meal_still(self):
        once = [Pick(candidate="omelette"), None, None]
        self.assertEqual(options(day(1), once, 1), options(day(None), once, 1))

    def test_what_cannot_be_asked(self):
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                day(bad)
        with self.assertRaises(ValueError):
            day(2, repeats=-1.0)


class TheBestWeek(unittest.TestCase):
    def test_a_light_weight_still_repeats_a_heavy_one_keeps_to_it_and_every_search_agrees(self):
        self.assertEqual(most_meals(day(None), oracle(day(None)).best), 3)
        self.assertEqual(most_meals(day(1, repeats=0.05), oracle(day(1, repeats=0.05)).best), 3)
        for tolerance in (1, 2):
            self.assertLessEqual(most_meals(day(tolerance, repeats=10.0), oracle(day(tolerance, repeats=10.0)).best), tolerance)
        for tolerance in (1, 2, 3):
            for weight in (0.5, 1.0, 10.0):
                p = day(tolerance, repeats=weight)
                best = oracle(p).best
                for result in (exact(p), beam(p), auto(p, time_limit_s=2), improve(p, evaluate(p, oracle(day(None)).best.picks))):
                    self.assertAlmostEqual(result.best.objective, best.objective, msg=(tolerance, weight, result.method))

    def test_the_bound_never_falls_below_what_a_week_comes_to(self):
        rng = random.Random(7)
        p = day(1, repeats=2.0)
        for _ in range(200):
            partial = [None] * 3
            for i in range(3):
                partial[i] = rng.choice(options(p, partial, i))
            final = evaluate(p, partial).objective
            for k in range(4):
                self.assertGreaterEqual(prefix_bound(p, partial[:k] + [None] * (3 - k)).objective, final - 1e-9)

    def test_the_report_says_the_most_and_what_it_cost(self):
        p = day(1, repeats=0.05)
        text = describe_plan(p, oracle(p).best)
        self.assertIn("repeats: 1 meal(s) of one recipe tolerated this week; the most, 3: buttered pasta; 2 meal(s) over, 0.1 point(s) off", text)


def tolerant(seed: int):
    """A random problem (its weights draw no repeats weight, so 1) at a tolerance of 1 or 2."""
    return replace(random_problem(seed), repeat_tolerance=1 + seed % 2, _cache={})


class RandomWeeks(unittest.TestCase):
    def test_the_exact_search_agrees_with_the_oracle(self):
        priced = 0
        for seed in SEEDS:
            p = tolerant(seed)
            for relaxed in (False, True):
                want, got = oracle(p, relaxed=relaxed), exact(p, relaxed=relaxed)
                self.assertEqual(want.best is None, got.best is None, (seed, relaxed))
                if want.best:
                    self.assertAlmostEqual(want.best.objective, got.best.objective, delta=TOL, msg=(seed, relaxed))
            free = oracle(random_problem(seed)).best
            priced += free is not None and abs(evaluate(p, free.picks).objective - free.objective) > TOL
        self.assertGreater(priced, 5)              # the term genuinely prices some weeks' best plans


class TheWeekFile(unittest.TestCase):
    def test_read_and_checked(self):
        week = read(WEEK + "repeat_tolerance = 2\n[weights]\nrepeats = 1.5\n")
        self.assertEqual((week["repeat_tolerance"], week["weights"]["repeats"]), (2, 1.5))
        self.assertIsNone(read(WEEK).get("repeat_tolerance"))
        for bad in ("0", "1.5", '"twice"', "true"):
            with self.assertRaises(tool.WeekError) as caught:
                read(WEEK + f"repeat_tolerance = {bad}\n")
            self.assertIn("repeat_tolerance is how many meals of the week one recipe may be", " ".join(caught.exception.args[0]))
        with self.assertRaises(tool.WeekError):
            read(WEEK + "[weights]\nrepeats = -1\n")

    def test_a_recipe_asked_for_more_often_than_tolerated_is_only_priced(self):
        self.assertEqual(len(read(WEEK + 'repeat_tolerance = 1\ncook = ["Omelette", "Omelette"]\n')["requests"]), 2)


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_cpsat_prices_repeats_as_the_oracle_does(self):
        for tolerance in (1, 2, 3):
            for weight in (0.5, 10.0):
                p = day(tolerance, repeats=weight)
                result = cpsat.solve(p)
                self.assertAlmostEqual(result.best.objective, oracle(p).best.objective, msg=(tolerance, weight))
                self.assertGreaterEqual(result.upper_bound, oracle(p).best.objective - CEILING_TOL)

    def test_cpsat_agrees_on_random_weeks(self):
        for seed in SEEDS:
            p = tolerant(seed)
            want, got = oracle(p), cpsat.solve(p)
            self.assertEqual(want.best is None, got.best is None, seed)
            if want.best:
                self.assertGreaterEqual(got.upper_bound, want.best.objective - CEILING_TOL, f"seed {seed}: the ceiling is below the optimum")
                if stock_is_exact(p):
                    self.assertAlmostEqual(got.best.objective, want.best.objective, delta=TOL, msg=seed)

    def test_a_recipe_only_committed_meals_take_over_puts_its_cost_on_the_ceiling(self):
        """The omelette is a breakfast and the open meals are lunch and dinner, so no variable can
        choose it: its two committed meals, one over, are a constant the proven ceiling must carry."""
        tagged = tuple(replace(c, meal_types=frozenset({"Breakfast"} if c.id == "omelette" else {"Lunch", "Dinner"})) for c in KEPT)
        breakfast = Fixed(candidate="omelette", cooked=2.0, name="omelette, committed")
        slots = [slot("breakfast", when(28, 8), "Breakfast", fixed=breakfast),
                 slot("brunch", when(28, 10), "Breakfast", fixed=Fixed(source=0, name="omelette leftovers")),
                 slot("lunch", when(28, 12), "Lunch"), slot("dinner", when(28, 18), "Dinner")]
        p = problem(slots, tagged, weights=replace(WEIGHTS, repeats=2.0), repeat_tolerance=1)
        want, got = oracle(p).best, cpsat.solve(p)
        self.assertAlmostEqual(want.terms["repeats"], -2.0)
        self.assertTrue(got.proven)
        self.assertAlmostEqual(got.upper_bound, want.objective, delta=CEILING_TOL)

    def test_committed_meals_count_in_cpsat_too(self):
        for fixed_meals in (1, 2):
            breakfast = Fixed(candidate="omelette", cooked=2.0, name="omelette, committed")
            slots = [slot("breakfast", when(28, 8), fixed=breakfast)]
            if fixed_meals == 2:
                slots.append(slot("brunch", when(28, 10), fixed=Fixed(source=0, name="omelette leftovers")))
            slots += [slot("lunch", when(28, 12)), slot("dinner", when(28, 18))]
            p = problem(slots, KEPT, weights=WEIGHTS, repeat_tolerance=1)
            result = cpsat.solve(p)
            self.assertAlmostEqual(result.best.objective, oracle(p).best.objective, msg=fixed_meals)
            self.assertGreaterEqual(result.upper_bound, oracle(p).best.objective - CEILING_TOL, msg=fixed_meals)


if __name__ == "__main__":
    unittest.main()
