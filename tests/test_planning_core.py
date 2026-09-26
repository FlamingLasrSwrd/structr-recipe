"""evaluate() and the oracle on hand-worked cases.

The worked day is the one in docs/optimizer-design.md Sec 2: three slots, five
recipes, a hard daily protein minimum. Every expected number below is worked out
here from the recipes' figures, not read back from the planner:

  time fit with a 30-minute budget (1 within it, then 1 - overage/30):
      pasta 20 min -> 1     stir-fry 25 -> 1     omelette 35 -> 1 - 5/30 = 5/6
      chicken salad 40 -> 1 - 10/30 = 2/3        braised chicken 90 -> max(0, 1 - 60/30) = 0
"""

import itertools
import unittest

from mealplanner.planning.evaluate import (
    allocate_stock, evaluate, initial_partial, ineligible_reason, leftover_reason, options, resolve,
)
from mealplanner.planning.model import Fixed, Lot, Pick, Weights
from mealplanner.planning.search import oracle
from tests.planning_fixtures import MEALS, cand, day_of_three, problem, protein_target, slot, when

TIME_FIT = {"buttered pasta": 1.0, "veggie stir-fry": 1.0, "omelette": 5 / 6, "chicken salad": 2 / 3, "braised chicken": 0.0}
PROTEIN = {"buttered pasta": 12, "veggie stir-fry": 10, "omelette": 24, "chicken salad": 30, "braised chicken": 45}


def picks(*names):
    return tuple(Pick(candidate=n) for n in names)


class TheWorkedDay(unittest.TestCase):
    """Hard daily protein minimum 70 g, maximum 140 g, weight 0.2; time weight 0.6."""

    def setUp(self):
        self.p = day_of_three([protein_target(70, 140, weight=0.2)])

    def test_the_greedy_menu_is_infeasible_by_34_grams(self):
        ev = evaluate(self.p, picks("buttered pasta", "buttered pasta", "buttered pasta"))
        (violation,) = ev.violations
        self.assertEqual((violation.kind, violation.total, violation.bound), ("below_min", 36, 70))
        self.assertAlmostEqual(violation.measure, 34 / 70)
        self.assertFalse(ev.feasible)

    def test_three_omelettes_meet_the_minimum_and_score_as_worked_by_hand(self):
        ev = evaluate(self.p, picks("omelette", "omelette", "omelette"))
        self.assertTrue(ev.feasible)                       # 72 g
        self.assertAlmostEqual(ev.terms["time"], 0.6 * 3 * 5 / 6)          # 1.5
        self.assertAlmostEqual(ev.terms["nutrition"], 0.2 * 1.0)           # judged ONCE, in range
        self.assertAlmostEqual(ev.objective, 1.7)

    def test_the_oracle_counts_63_of_125_menus_feasible_and_finds_the_best(self):
        # counted independently: ordered triples of the five protein figures summing to at least 70
        feasible = sum(1 for t in itertools.product(PROTEIN.values(), repeat=3) if 70 <= sum(t) <= 140)
        best = max(0.6 * sum(TIME_FIT[m] for m in menu) + 0.2
                   for menu in itertools.product(PROTEIN, repeat=3) if 70 <= sum(PROTEIN[m] for m in menu) <= 140)
        self.assertEqual(feasible, 63)
        result = oracle(self.p)
        self.assertEqual((result.total_count, result.feasible_count), (125, 63))
        self.assertAlmostEqual(result.best.objective, best)
        self.assertAlmostEqual(best, 1.7)

    def test_no_single_swap_repairs_the_greedy_day(self):
        greedy = ["buttered pasta"] * 3
        for slot_index, replacement in itertools.product(range(3), PROTEIN):
            menu = list(greedy)
            menu[slot_index] = replacement
            self.assertFalse(evaluate(self.p, picks(*menu)).feasible, (slot_index, replacement))

    def test_a_scoped_target_is_judged_once_not_per_slot(self):
        # weight 0.2 appears once in the objective for the day, not three times
        ev = evaluate(self.p, picks("omelette", "omelette", "omelette"))
        self.assertAlmostEqual(ev.terms["nutrition"], 0.2)


class Unreachable(unittest.TestCase):
    def test_a_minimum_above_what_any_menu_can_reach(self):
        p = day_of_three([protein_target(140, None)])            # the most possible is 3 x 45 = 135
        result = oracle(p)
        self.assertEqual((result.feasible_count, result.best), (0, None))

    def test_relaxed_mode_finds_the_closest_plan(self):
        p = day_of_three([protein_target(140, None)])
        result = oracle(p, relaxed=True)
        self.assertEqual([pick.candidate for pick in result.best.picks], ["braised chicken"] * 3)
        self.assertAlmostEqual(result.best.violation_measure, 5 / 140)


class Scopes(unittest.TestCase):
    def two_days(self, target):
        return problem([slot("d1 a", when(28, 8)), slot("d1 b", when(28, 18)), slot("d2 a", when(29, 8)), slot("d2 b", when(29, 18))],
                       MEALS, [target])

    def test_daily_groups_are_judged_separately(self):
        p = self.two_days(protein_target(60, None, scope="daily"))
        # day 1: 45 + 45 = 90; day 2: 12 + 10 = 22 -> only day 2 falls short
        ev = evaluate(p, picks("braised chicken", "braised chicken", "buttered pasta", "veggie stir-fry"))
        self.assertEqual([(v.group, v.kind) for v in ev.violations], [("2026-09-29", "below_min")])

    def test_weekly_is_one_group(self):
        p = self.two_days(protein_target(100, None, scope="weekly"))
        ev = evaluate(p, picks("braised chicken", "braised chicken", "buttered pasta", "veggie stir-fry"))
        self.assertTrue(ev.feasible)                                # 90 + 22 = 112

    def test_per_meal_judges_every_slot(self):
        p = self.two_days(protein_target(20, None, scope="per_meal"))
        ev = evaluate(p, picks("omelette", "buttered pasta", "chicken salad", "omelette"))
        self.assertEqual([v.group for v in ev.violations], ["d1 b"])          # 12 g < 20


class UnknownAndUntrustedData(unittest.TestCase):
    """A hard target is never decided on data that is missing, placeholder or unmarked."""

    def test_a_recipe_with_no_figure_is_ineligible(self):
        p = day_of_three([protein_target(70, None)], candidates=MEALS + (cand("mystery", None, 10),))
        self.assertIn("no Protein data", ineligible_reason(p, 0, p.candidates["mystery"]))
        self.assertNotIn(Pick(candidate="mystery"), options(p, initial_partial(p), 0))

    def test_a_placeholder_figure_is_ineligible(self):
        shaky = cand("shaky", 60, 10, untrusted=frozenset({"protein"}))
        p = day_of_three([protein_target(70, None)], candidates=(shaky,))
        self.assertIn("placeholder", ineligible_reason(p, 0, shaky))
        self.assertEqual(oracle(p).total_count, 0)                   # nothing can fill the slots

    def test_without_a_hard_target_the_same_recipe_is_fine(self):
        shaky = cand("shaky", 60, 10, untrusted=frozenset({"protein"}))
        p = day_of_three([protein_target(70, None, hard=False, weight=0.2)], candidates=(shaky,))
        self.assertIsNone(ineligible_reason(p, 0, shaky))


class FixedEntries(unittest.TestCase):
    def test_a_fixed_entry_counts_towards_the_group_and_cannot_change(self):
        p = problem([slot("lunch", when(28, 12), fixed=Fixed(eaten=1.0, candidate="chicken salad")), slot("dinner", when(28, 18))],
                    MEALS, [protein_target(70, None)])
        result = oracle(p)
        # 30 g is already there, so dinner needs 40 g: omelette (24) and salad (30) are not enough alone;
        # only braised chicken (45) works
        self.assertEqual([pick.candidate for pick in result.best.picks], ["chicken salad", "braised chicken"])
        self.assertEqual(result.feasible_count, 1)

    def test_evaluate_refuses_a_changed_fixed_entry(self):
        p = problem([slot("lunch", when(28, 12), fixed=Fixed(eaten=1.0, candidate="chicken salad"))], MEALS)
        ev = evaluate(p, picks("omelette"))
        self.assertFalse(ev.legal)
        self.assertIn("fixed entry cannot be changed", ev.problems[0])

    def test_a_fixed_entry_with_no_figure_makes_a_hard_group_unverifiable(self):
        mystery = cand("mystery", None, 10)
        p = problem([slot("lunch", when(28, 12), fixed=Fixed(eaten=1.0, candidate="mystery")), slot("dinner", when(28, 18))],
                    (mystery,) + MEALS, [protein_target(None, 200)])
        ev = evaluate(p, picks("mystery", "braised chicken"))
        self.assertEqual([v.kind for v in ev.violations], ["unverifiable"])     # the maximum cannot be certified


class Leftovers(unittest.TestCase):
    """Slow recipes score 0 on time (budget 30, they take 90 or 60); a leftover slot needs no cooking and scores 1."""

    def stew_problem(self, second_start=when(29, 18), leftover_days=3.0):
        stew = cand("stew", 40, 90, yield_servings=4.0, leftover_days=leftover_days)
        roast = cand("roast", 40, 60, yield_servings=4.0)
        return problem([slot("mon", when(28, 18)), slot("tue", second_start)], [stew, roast], [])

    def test_cooking_once_and_eating_it_twice_beats_cooking_twice(self):
        p = self.stew_problem()
        result = oracle(p)
        self.assertEqual(result.best.picks, (Pick(candidate="stew"), Pick(source=0)))
        self.assertAlmostEqual(result.best.objective, 0.6 * (0.0 + 1.0))       # stew 0, leftover 1
        self.assertEqual(result.total_count, 5)                # stew/roast x stew/roast (4) + stew then its leftover

    def test_servings_cooked_are_derived_from_what_is_eaten(self):
        p = self.stew_problem()
        _, cooked = resolve(p, [Pick(candidate="stew"), Pick(source=0)])
        self.assertEqual(cooked, [2.0, 0.0])

    def test_not_before_it_is_cooked(self):
        p = self.stew_problem(second_start=when(28, 19))                       # 60 minutes after a 90-minute cook
        resolved, _ = resolve(p, [Pick(candidate="stew"), None])
        self.assertEqual(leftover_reason(p, resolved, 0, 1), "not cooked yet")

    def test_not_past_its_keeping_time(self):
        p = self.stew_problem(second_start=when(30, 19), leftover_days=1.0)
        resolved, _ = resolve(p, [Pick(candidate="stew"), None])
        self.assertEqual(leftover_reason(p, resolved, 0, 1), "past its keeping time")

    def test_a_recipe_with_no_keeping_time_has_no_leftovers(self):
        p = self.stew_problem()
        resolved, _ = resolve(p, [Pick(candidate="roast"), None])
        self.assertEqual(leftover_reason(p, resolved, 0, 1), "leftovers of this recipe are not planned")

    def test_a_leftover_slot_may_have_any_meal_type(self):
        stew = cand("stew", 40, 90, yield_servings=4.0, leftover_days=3.0, meal_types=frozenset({"Dinner"}))
        p = problem([slot("mon dinner", when(28, 18), "Dinner"), slot("tue lunch", when(29, 12), "Lunch")], [stew])
        self.assertEqual(oracle(p).best.picks, (Pick(candidate="stew"), Pick(source=0)))    # no fresh cook may fill lunch

    def test_a_leftover_slot_does_not_cook_a_second_batch_of_stock(self):
        p = self.stew_problem()
        ev = evaluate(p, (Pick(candidate="stew"), Pick(source=0)))
        self.assertEqual([d["cooked_servings"] for d in ev.slot_details], [2.0, 0.0])


class Variety(unittest.TestCase):
    def two_slots(self, gap_days, uses=()):
        soup = cand("soup", 10, 10, uses=tuple(uses))
        return problem([slot("a", when(28, 18)), slot("b", when(28 + gap_days, 18))], [soup],
                       weights=Weights(time=0.0, variety=1.0, time_budget_minutes=30.0))

    def test_the_same_recipe_seven_days_apart_scores_half_each(self):
        ev = evaluate(self.two_slots(7), picks("soup", "soup"))
        self.assertAlmostEqual(ev.terms["variety"], 0.5 + 0.5)             # 7 / 14 each

    def test_beyond_fourteen_days_is_full_marks(self):
        ev = evaluate(self.two_slots(20), picks("soup", "soup"))
        self.assertAlmostEqual(ev.terms["variety"], 2.0)

    def test_an_outside_use_counts_even_for_a_single_slot(self):
        p = problem([slot("a", when(28, 18))], [cand("soup", 10, 10, uses=(when(25, 18),))], weights=Weights(time=0.0, variety=1.0))
        self.assertAlmostEqual(evaluate(p, picks("soup")).terms["variety"], 3 / 14)

    def test_the_nearest_use_decides(self):
        p = problem([slot("a", when(28, 18))], [cand("soup", 10, 10, uses=(when(25, 18), when(27, 18)))], weights=Weights(time=0.0, variety=1.0))
        self.assertAlmostEqual(evaluate(p, picks("soup")).terms["variety"], 1 / 14)

    def test_soft_exclusion_costs_its_weight_per_use(self):
        p = problem([slot("a", when(28, 18)), slot("b", when(29, 18))], [cand("nutty", 10, 10, soft_penalty=0.3)],
                    weights=Weights(time=0.0, variety=0.0))
        self.assertAlmostEqual(evaluate(p, picks("nutty", "nutty")).terms["soft_exclusion"], -0.6)


class SoftTargets(unittest.TestCase):
    def test_a_soft_target_scores_the_selectors_fit_once_on_the_final_total(self):
        p = day_of_three([protein_target(100, None, hard=False, weight=0.5)], weights=Weights(time=0.0, variety=0.0))
        ev = evaluate(p, picks("omelette", "omelette", "omelette"))              # 72 g against a minimum of 100
        self.assertAlmostEqual(ev.terms["nutrition"], 0.5 * (1 - 28 / 100))
        self.assertTrue(ev.feasible)                                              # soft: never a violation


class Stock(unittest.TestCase):
    """One pool 'chicken'. A recipe (yield 4) needs 400 g of it for the whole batch."""

    def build(self, lots, servings=1.0, second=False):
        roast = cand("roast", 40, 20, yield_servings=4.0, demand={"chicken": 400.0})
        slots = [slot("mon", when(28, 18))] + ([slot("tue", when(29, 18))] if second else [])
        return problem(slots, [roast], lots=lots, servings_eaten=servings,
                       weights=Weights(time=0.0, variety=0.0, stock=1.0, waste=1.0, time_budget_minutes=30.0))

    def test_partial_coverage_is_the_fraction_of_the_need_met(self):
        # one serving of four needs 100 g; 60 g is on hand
        p = self.build([Lot("chicken", 60.0, when(30, 18))])
        ev = evaluate(p, picks("roast"))
        self.assertAlmostEqual(ev.terms["stock"], 0.6)

    def test_urgency_is_the_selectors_from_the_soonest_lot_still_good(self):
        # expires 2 days after the cook: 1 - 2/5 = 0.6
        p = self.build([Lot("chicken", 500.0, when(30, 18))])
        self.assertAlmostEqual(evaluate(p, picks("roast")).terms["waste"], 0.6)

    def test_a_lot_that_expires_before_the_cook_is_no_use(self):
        p = self.build([Lot("chicken", 500.0, when(28, 12))])
        ev = evaluate(p, picks("roast"))
        self.assertAlmostEqual(ev.terms["stock"], 0.0)
        self.assertAlmostEqual(ev.terms["waste"], 0.0)

    def test_two_cooks_share_the_pool_in_time_order(self):
        # each cook needs 100 g; 150 g is on hand: the first is covered, the second gets half
        p = self.build([Lot("chicken", 150.0, when(30, 18))], second=True)
        stock = allocate_stock(p, *resolve(p, [Pick(candidate="roast"), Pick(candidate="roast")]))
        self.assertAlmostEqual(stock[0][0], 1.0)
        self.assertAlmostEqual(stock[1][0], 0.5)

    def test_the_soonest_expiring_lot_is_used_first(self):
        lots = [Lot("chicken", 100.0, when(31, 18), "later"), Lot("chicken", 100.0, when(29, 12), "sooner")]
        p = self.build(lots, second=True)
        # Monday's cook takes the lot expiring Tuesday noon; Tuesday's cook (after noon) then can only use the later one
        stock = allocate_stock(p, *resolve(p, [Pick(candidate="roast"), Pick(candidate="roast")]))
        self.assertAlmostEqual(stock[0][0], 1.0)
        self.assertAlmostEqual(stock[1][0], 1.0)

    def test_no_stock_or_no_demand_leaves_the_term_at_zero(self):
        p = self.build([])
        self.assertAlmostEqual(evaluate(p, picks("roast")).terms["stock"], 0.0)


class ProblemsAreValidated(unittest.TestCase):
    def test_slot_keys_must_be_unique(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            problem([slot("dinner", when(28, 18)), slot("dinner", when(29, 18))], MEALS)

    def test_slot_times_must_carry_a_timezone(self):
        from datetime import datetime
        with self.assertRaisesRegex(ValueError, "timezone"):
            problem([slot("dinner", datetime(2026, 9, 28, 18))], MEALS)

    def test_slots_must_be_in_time_order(self):
        with self.assertRaisesRegex(ValueError, "chronological"):
            problem([slot("later", when(29, 18)), slot("earlier", when(28, 18))], MEALS)

    def test_negative_weights_are_refused(self):
        with self.assertRaisesRegex(ValueError, "negative"):
            problem([slot("a", when(28, 18))], MEALS, weights=Weights(time=-0.1))


if __name__ == "__main__":
    unittest.main()
