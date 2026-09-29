"""Planning for a household: one recipe per shared meal, a portion per eater, each person's own targets
and baseline (data-model.md Sec 19 K5; mealplanner/planning/).

Worked out by hand. One shared dinner on day 28. Stew has 20 g protein a serving, salad 10 g.
  A eats 1 or 1.5 servings and needs at least 25 g of protein a day (hard).
  B eats 0.5 or 1 serving and may have at most 12 g (hard).
  Stew:  A 1.5 -> 30 g (A 1.0 -> 20 g is short); B 0.5 -> 10 g (B 1.0 -> 20 g is over). So (1.5, 0.5) only.
  Salad: A 1.5 -> 15 g, short. Never feasible.
The only feasible plan is stew with shares (1.5, 0.5): 2.0 servings cooked.
"""

import unittest
from dataclasses import replace

from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, group_states, options, resolve, slot_max_intake
from mealplanner.planning.nutrients import slot_reach, standings
from mealplanner.planning.model import Fixed, Pick, Target
from mealplanner.planning.nutrients import describe_nutrients
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import auto, exact, oracle
from tests.planning_fixtures import cand, problem, slot, when

STEW, SALAD = cand("stew", 20, 30, leftover_days=3.0, meal_types=frozenset({"Dinner", "Lunch"})), cand("salad", 10, 10, meal_types=frozenset({"Dinner"}))
A_MIN = Target("A protein", "protein", "daily", 25, None, True, 0.0, "Protein", eater="a")
B_MAX = Target("B protein", "protein", "daily", None, 12, True, 0.0, "Protein", eater="b")


def household(slots=None, targets=(A_MIN, B_MAX), **kw):
    kw.setdefault("eater_portions", {"a": (1.0, 1.5), "b": (0.5, 1.0)})
    kw.setdefault("eater_names", {"a": "Ari", "b": "Bo"})
    return problem(slots or [slot("dinner", when(28, 18), "Dinner")], [STEW, SALAD], targets, eaters=("a", "b"), **kw)


class SharedMeal(unittest.TestCase):
    def test_the_only_feasible_plan_is_found_by_every_search(self):
        p = household()
        want = oracle(p)
        self.assertEqual(want.feasible_count, 1)
        self.assertEqual(want.best.picks, (Pick(candidate="stew", shares=(1.5, 0.5)),))
        for result in (exact(p), auto(p, time_limit_s=5.0)):
            self.assertEqual(result.best.picks, want.best.picks)

    def test_a_shared_slot_offers_every_combination_of_portions(self):
        self.assertEqual(len(options(household(), [None], 0)), 2 * 2 * 2)          # recipes x A's levels x B's

    def test_each_person_counts_only_their_own_share(self):
        p = household()
        resolved, cooked = resolve(p, [Pick(candidate="stew", shares=(1.5, 1.0))])
        self.assertEqual((resolved[0].eaten, cooked[0]), (2.5, 2.5))
        totals = {g.target.name: g.total for g in group_states(p, resolved)}
        self.assertEqual(totals, {"A protein": 30.0, "B protein": 20.0})
        ev = evaluate(p, [Pick(candidate="stew", shares=(1.5, 1.0))])
        self.assertEqual([(v.target, v.kind, v.total) for v in ev.violations], [("B protein", "above_max", 20.0)])

    def test_a_meal_one_person_eats_counts_for_them_alone_and_leftovers_add_to_the_cook(self):
        slots = [slot("dinner", when(28, 18), "Dinner"), slot("lunch", when(29, 12), "Lunch", eaters=("a",))]
        p = household(slots, targets=(replace(A_MIN, minimum=None), replace(B_MAX, maximum=None)))
        picks = [Pick(candidate="stew", shares=(1.0, 0.5)), Pick(source=0, portion=1.5)]
        resolved, cooked = resolve(p, picks)
        self.assertEqual(cooked[0], 3.0)                                             # 1.0 + 0.5 + 1.5
        totals = {(g.target.name, g.label): g.total for g in group_states(p, resolved)}
        self.assertEqual(totals[("A protein", "2026-09-29")], 30.0)                  # the lunch, A's alone
        self.assertEqual(totals[("B protein", "2026-09-29")], 0.0)
        self.assertEqual(totals[("B protein", "2026-09-28")], 10.0)

    def test_each_person_has_their_own_baseline(self):
        p = household(baselines={"a": {"protein": 5.0}})
        resolved, _ = resolve(p, [Pick(candidate="stew", shares=(1.0, 0.5))])
        totals = {g.target.name: g.total for g in group_states(p, resolved)}
        self.assertEqual(totals, {"A protein": 25.0, "B protein": 10.0})              # 20 + 5, and 10 + nothing
        self.assertTrue(evaluate(p, [Pick(candidate="stew", shares=(1.0, 0.5))]).feasible)

    def test_a_committed_meal_keeps_who_ate_what(self):
        fixed = Fixed(eaten=2.0, candidate="stew", cooked=2.0, shares=(("a", 1.5), ("b", 0.5)))
        p = household([slot("dinner", when(28, 18), "Dinner", fixed=fixed)])
        resolved, _ = resolve(p, [Pick(candidate="stew")])
        self.assertEqual({g.target.name: g.total for g in group_states(p, resolved)}, {"A protein": 30.0, "B protein": 10.0})


class Bounds(unittest.TestCase):
    def test_the_most_a_person_can_eat_uses_their_own_levels_and_is_nothing_where_they_do_not_eat(self):
        slots = [slot("dinner", when(28, 18), "Dinner"), slot("lunch", when(29, 12), "Lunch", eaters=("a",))]
        p = household(slots)
        self.assertEqual((slot_max_intake(p, 0, "protein", "a"), slot_max_intake(p, 0, "protein", "b")), (30.0, 20.0))
        self.assertEqual(slot_max_intake(p, 1, "protein", "b"), 0.0)

    def test_a_day_with_no_open_meal_for_a_person_adds_nothing_to_the_score(self):
        fixed = Fixed(eaten=1.0, candidate="stew", cooked=1.0, shares=(("b", 1.0),))
        slots = [slot("lunch", when(28, 12), "Dinner", eaters=("a",)), slot("dinner", when(28, 18), "Dinner", fixed=fixed, eaters=("b",))]
        soft_b = Target("B protein", "protein", "daily", 30, None, False, 1.0, "Protein", eater="b")
        p = household(slots, targets=(soft_b,))
        ev = evaluate(p, [Pick(candidate="salad", portion=1.0), Pick(candidate="stew")])
        self.assertTrue(ev.legal, ev.problems)
        self.assertEqual(ev.terms["nutrition"], 0.0)          # B's day holds only B's committed dinner

    def test_what_cannot_be_met_counts_only_the_meals_a_person_eats(self):
        # B eats only a committed dinner of 20 g and needs 30 g: impossible, whatever A's open lunch holds
        fixed = Fixed(eaten=1.0, candidate="stew", cooked=1.0, shares=(("b", 1.0),))
        slots = [slot("lunch", when(28, 12), "Dinner", eaters=("a",)), slot("dinner", when(28, 18), "Dinner", fixed=fixed, eaters=("b",))]
        b_min = Target("B protein", "protein", "daily", 30, None, False, 1.0, "Protein", eater="b")
        p = household(slots, targets=(b_min,))
        ev = evaluate(p, [Pick(candidate="stew", portion=1.5), Pick(candidate="stew")])
        (b,) = standings(p, ev)
        self.assertEqual((b.impossible, b.reach), (1, [(20.0, 20.0)]))
        self.assertEqual(slot_reach(p, 0, "protein", "b"), (0.0, 0.0))            # the lunch is A's alone
        self.assertEqual(slot_reach(p, 0, "protein", "a"), (10.0, 30.0))          # salad at 1.0 to stew at 1.5


@unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
class CpSat(unittest.TestCase):
    def test_it_finds_the_only_feasible_shares(self):
        got = cpsat.solve(household())
        self.assertEqual(got.best.picks, (Pick(candidate="stew", shares=(1.5, 0.5)),))
        self.assertTrue(got.proven)


class Checks(unittest.TestCase):
    def test_a_pick_that_does_not_fit_the_eaters_is_illegal(self):
        p = household()
        for pick, text in ((Pick(candidate="stew", portion=1.0), "give shares"),
                           (Pick(candidate="stew", shares=(1.5,)), "1 shares for 2 eaters"),
                           (Pick(candidate="stew", shares=(1.5, 1.5)), "a share of 1.5 for Bo")):
            ev = evaluate(p, [pick])
            self.assertFalse(ev.legal, pick)
            self.assertIn(text, " ".join(ev.problems))

    def test_unknown_eaters_are_refused(self):
        with self.assertRaises(ValueError):
            household([slot("dinner", when(28, 18), "Dinner", eaters=("c",))])
        with self.assertRaises(ValueError):
            household(targets=(replace(A_MIN, eater="c"),))

    def test_a_problem_without_eaters_is_one_unnamed_eater(self):
        p = problem([slot("dinner", when(28, 18), "Dinner")], [STEW], [replace(A_MIN, eater="")], portions=(1.0, 1.5))
        self.assertEqual([o.portion for o in options(p, [None], 0)], [1.0, 1.5])
        self.assertEqual(oracle(p).best.picks, (Pick(candidate="stew", portion=1.5),))


class Words(unittest.TestCase):
    def test_the_report_names_who_eats_how_much(self):
        p = household()
        ev = evaluate(p, [Pick(candidate="stew", shares=(1.5, 0.5))])
        self.assertIn("cook stew for 2 servings, eat 1.5 Ari, 0.5 Bo", describe_plan(p, ev))
        nutrients = describe_nutrients(p, ev)
        self.assertIn("Protein (Ari)", nutrients)
        self.assertIn("Protein (Bo)", nutrients)


if __name__ == "__main__":
    unittest.main()
