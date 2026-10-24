"""Meal-prep sessions (planning/model.PrepSession, Pick.prep; docs/optimizer-design.md Sec 12).

Three dinners, Mon 28 to Wed 30 at 18:00, and a prep session on Sun 27 at 14:00. Only the time term is
weighted, against a 30-minute budget, and every recipe takes longer, so a meal is worth more the less
is cooked at it: made at the session (or eaten as leftovers) it scores 1. Cooked food keeps 3 days,
so a dish made on Sunday at 14:00 keeps until Wednesday at 14:00: Monday and Tuesday may eat it,
Wednesday may not.
"""

import random
import unittest
from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, options, prefix_bound
from mealplanner.planning.model import Fixed, Pick, PrepSession, Target
from mealplanner.planning.search import auto, beam, exact, improve, oracle
from tests.planning_fixtures import cand, problem, slot, when

STEW = cand("stew", 30, 90, leftover_days=3.0)
CURRY = cand("curry", 25, 60, leftover_days=3.0)
SOUFFLE = cand("souffle", 20, 45)                       # not kept: eaten when made, so never made ahead
DINNERS = [slot("Mon", when(28)), slot("Tue", when(29)), slot("Wed", when(30))]


def week(minutes=180.0, dishes=2, start=None, candidates=(STEW, CURRY, SOUFFLE), slots=DINNERS, **kw):
    session = PrepSession("Sun prep", start or when(27, 14), minutes, dishes)
    return problem(slots, candidates, preps=(session,), now=when(26, 9), **kw)


def prepped(ev):
    return [(i, p.candidate) for i, p in enumerate(ev.picks) if p.prep is not None]


class WhenADishMayBeMadeAhead(unittest.TestCase):
    def test_a_kept_dish_feeds_monday_and_tuesday_but_not_wednesday(self):
        p = week()
        made = {(i, pick.candidate) for i in range(3) for pick in options(p, [None] * 3, i) if pick.prep is not None}
        self.assertEqual(made, {(0, "stew"), (0, "curry"), (1, "stew"), (1, "curry")})

    def test_the_leftovers_of_a_dish_made_ahead_keep_from_the_session(self):
        p = week()
        partial = [Pick(candidate="stew", prep=0), None, None]
        self.assertFalse([pick for pick in options(p, partial, 2) if pick.source == 0])   # past Sunday's keeping time
        self.assertIn(Pick(source=0), options(p, partial, 1))

    def test_not_ready_in_time_past_or_too_long_for_the_session(self):
        late = week(start=when(28, 17), slots=[slot("Mon", when(28))])     # stew's 90 minutes from 17:00 end past 18:00
        self.assertEqual({p.candidate for p in options(late, [None], 0) if p.prep is not None}, {"curry"})
        past = week(start=when(25, 14))                    # before the plan is made
        self.assertFalse([p for p in options(past, [None] * 3, 0) if p.prep is not None])
        short = week(minutes=60.0)
        self.assertEqual({p.candidate for p in options(short, [None] * 3, 0) if p.prep is not None}, {"curry"})


class TheSessionsBudget(unittest.TestCase):
    def test_a_session_full_of_dishes_takes_no_more(self):
        p = week(dishes=1)
        partial = [Pick(candidate="stew", prep=0), None, None]
        self.assertFalse([pick for pick in options(p, partial, 1) if pick.prep is not None])

    def test_its_minutes_are_shared(self):
        p = week(minutes=150.0)                           # stew 90 + curry 60 fit; stew + stew do not
        partial = [Pick(candidate="stew", prep=0), None, None]
        self.assertEqual({pick.candidate for pick in options(p, partial, 1) if pick.prep is not None}, {"curry"})

    def test_a_week_over_the_budget_is_not_legal(self):
        p = week(dishes=1)
        ev = evaluate(p, (Pick(candidate="stew", prep=0), Pick(candidate="curry", prep=0), Pick(candidate="curry")))
        self.assertFalse(ev.legal)
        self.assertIn("Sun prep: 2 dishes, more than its 1", ev.problems)


class TheBestWeek(unittest.TestCase):
    def test_prep_is_used_where_it_pays_and_every_search_agrees(self):
        p = week()
        best = oracle(p).best
        self.assertTrue(prepped(best))
        self.assertAlmostEqual(best.terms["time"], 0.6 * 2 + 0.6 * best.slot_details[2]["time_fit"])
        for result in (exact(p), beam(p), auto(p, time_limit_s=2), improve(p, evaluate(p, (Pick(candidate="curry"),) * 3))):
            self.assertAlmostEqual(result.best.objective, best.objective, msg=result.method)
        self.assertEqual({d["prep"] for d in best.slot_details if d["prep"]}, {"Sun prep"})

    def test_without_a_session_nothing_is_made_ahead(self):
        p = problem(DINNERS, (STEW, CURRY, SOUFFLE), now=when(26, 9))
        self.assertFalse(prepped(oracle(p).best))

    def test_the_bound_never_falls_below_what_a_week_comes_to(self):
        rng = random.Random(3)
        p = week()
        for _ in range(100):
            partial = [None] * 3
            for i in range(3):
                partial[i] = rng.choice(options(p, partial, i))
            final = evaluate(p, partial)
            for k in range(4):
                bound = prefix_bound(p, partial[:k] + [None] * (3 - k))
                self.assertGreaterEqual(bound.objective, final.objective - 1e-9)


class ASessionCommitted(unittest.TestCase):
    def test_a_dish_no_one_eats_is_not_a_day_judged(self):
        sunday = slot("Sun prep -- stew", when(27, 14), fixed=Fixed(candidate="stew", cooked=2.0, eaten=0.0))
        target = Target("protein", "protein", "daily", 20, None, True, 0.0, "Protein")
        p = problem([sunday] + DINNERS, (STEW, CURRY), targets=(target,), now=when(26, 9))
        best = oracle(p).best
        self.assertTrue(best.feasible)                    # Sunday, eating nothing, is not under its minimum
        self.assertIn(Pick(source=0), options(p, list(best.picks[:1]) + [None] * 3, 1))


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_cpsat_makes_ahead_as_the_oracle_does_and_keeps_the_budget(self):
        for p in (week(), week(dishes=1), week(minutes=60.0), week(minutes=150.0)):
            result = cpsat.solve(p)
            self.assertTrue(result.best.legal)
            self.assertAlmostEqual(result.best.objective, oracle(p).best.objective)


if __name__ == "__main__":
    unittest.main()
