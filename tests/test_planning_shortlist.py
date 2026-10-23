"""A weekly shortlist of recipes for a large book (mealplanner/planning/shortlist.py).

Worked out by hand. One eater; energy 2,000-2,200 kcal a day (hard), so a day is 2,100 kcal;
fibre at least 30 g (soft, weight 1), so 30 / 2,100 = 0.0143 g per kcal; sodium at most
2,300 mg (soft, weight 1), 1.095 mg per kcal. Every recipe is 500 kcal a serving.
  bean soup   fibre 15 g (0.03 per kcal, past the floor: 1), sodium 400 mg (0.8: 1)      2.00
  rice bowl   fibre 2 g (0.004: 0.004 / 0.0143 = 0.28), sodium 100 mg (1)               1.28
  ramen       fibre 5 g (0.01: 0.7), sodium 2,000 mg (4.0, past twice the cap: 0)        0.70
  mystery     fibre unknown (neutral 0.5), sodium 500 mg (1)                            1.50
"""

import unittest

from mealplanner.planning.model import Target, Weights
from mealplanner.planning.shortlist import choose, scores
from mealplanner.recipe_nutrition import calculate
from tests.fakegraph import WritableGraph
from tests.planning_fixtures import cand, problem, slot, when

DINNER, BREAKFAST = frozenset({"Dinner"}), frozenset({"Breakfast"})
NO_TIME = Weights(time=0.0, variety=0.0, stock=0.0, waste=0.0, time_budget_minutes=30.0)
ENERGY = Target("energy", "energy", "daily", 2000, 2200, True, 0.0, "Energy")
FIBRE = Target("fibre", "fibre", "daily", 30, None, False, 1.0, "Fibre")
SODIUM = Target("sodium", "sodium", "daily", None, 2300, False, 1.0, "Sodium")
UNITS = {"energy": "kcal", "fibre": "g", "sodium": "mg"}


def recipe(name, fibre, sodium, meal_types=DINNER, minutes=20, **kw):
    return cand(name, None, minutes, meal_types=meal_types, nutrients={"energy": 500.0, "fibre": fibre, "sodium": sodium}, **kw)


BOOK = [recipe("bean soup", 15.0, 400.0), recipe("rice bowl", 2.0, 100.0), recipe("ramen", 5.0, 2000.0),
        recipe("mystery", None, 500.0)]


def week(candidates=BOOK, targets=(ENERGY, FIBRE, SODIUM), slots=None, **kw):
    kw.setdefault("weights", NO_TIME)
    return problem(slots or [slot("d1", when(28, 18), "Dinner"), slot("d2", when(29, 18), "Dinner")], candidates,
                   targets, units=UNITS, **kw)


class Ranking(unittest.TestCase):
    def test_fit_per_calorie_to_each_target(self):
        got = scores(week())
        for name, want in (("bean soup", 2.0), ("rice bowl", 1 + 0.004 / (30 / 2100)), ("ramen", 0.7), ("mystery", 1.5)):
            self.assertAlmostEqual(got[name], want, msg=name)

    def test_a_target_the_baseline_meets_asks_nothing_more(self):
        got = scores(week(baseline={"fibre": 30.0}))
        self.assertAlmostEqual(got["rice bowl"], 2.0)
        self.assertAlmostEqual(got["ramen"], 1.0)

    def test_none_of_a_nutrient_the_baseline_covers_costs_nothing(self):
        bare = recipe("bare", 0.0, 100.0)
        self.assertAlmostEqual(scores(week(candidates=[bare], baseline={"fibre": 30.0}))["bare"], 2.0)
        self.assertAlmostEqual(scores(week(candidates=[bare]))["bare"], 1.0)

    def test_the_baseline_also_uses_up_a_cap(self):
        got = scores(week(baseline={"sodium": 1250.0}))      # 1,050 mg left: 0.5 mg per kcal; bean soup's 0.8 is 1.6 times it
        self.assertAlmostEqual(got["bean soup"], 1 + (2 - 0.8 / 0.5))

    def test_a_hard_target_weighs_one_and_time_and_soft_exclusions_count(self):
        hard_fibre = Target("fibre", "fibre", "daily", 30, None, True, 0.0, "Fibre")
        self.assertAlmostEqual(scores(week(targets=(ENERGY, hard_fibre)))["ramen"], 0.7)
        slow = recipe("slow stew", 15.0, 400.0, minutes=45, soft_penalty=0.3)
        got = scores(week(candidates=[slow], weights=Weights(time=0.6, variety=0.0, time_budget_minutes=30.0)))
        self.assertAlmostEqual(got["slow stew"], 0.6 * 0.5 + 2.0 - 0.3)    # 45 minutes against 30: time fit 0.5

    def test_without_an_energy_target_every_figure_is_neutral(self):
        got = scores(week(targets=(FIBRE, SODIUM)))
        self.assertEqual(set(got.values()), {1.0})

    def test_a_per_meal_or_weekly_target_and_a_zero_weight_are_left_out(self):
        weekly = Target("fibre a week", "fibre", "weekly", 210, None, False, 1.0, "Fibre")
        light = Target("fibre", "fibre", "daily", 30, None, False, 0.0, "Fibre")
        self.assertEqual(set(scores(week(targets=(ENERGY, weekly, light))).values()), {0.0})


class Choosing(unittest.TestCase):
    def test_twice_as_many_as_the_meal_type_has_slots_best_first(self):
        self.assertEqual(choose(week(), factor=1.0, coverage=0), {"bean soup", "mystery"})
        self.assertEqual(choose(week(), factor=1.5, coverage=0), {"bean soup", "mystery", "rice bowl"})
        self.assertEqual(len(choose(week(), factor=0.75, coverage=0)), 2)                 # 1.5 a meal type: rounded up

    def test_each_meal_type_has_its_own(self):
        oats = recipe("oats", 10.0, 50.0, meal_types=BREAKFAST)
        toast = recipe("toast", 3.0, 300.0, meal_types=BREAKFAST)
        slots = [slot("b", when(28, 8), "Breakfast"), slot("d", when(28, 18), "Dinner")]
        self.assertEqual(choose(week(candidates=BOOK + [oats, toast], slots=slots), factor=1.0, coverage=0), {"oats", "bean soup"})

    def test_the_richest_in_a_hard_minimum_stay_reachable(self):
        hard_fibre = Target("fibre", "fibre", "daily", 30, None, True, 0.0, "Fibre")
        rich = recipe("lentils", 25.0, 2500.0)           # ranks last on sodium, richest in fibre
        p = week(candidates=BOOK[:3] + [rich], targets=(ENERGY, hard_fibre, SODIUM))
        self.assertIn("lentils", choose(p, factor=0.5, coverage=1))
        self.assertNotIn("lentils", choose(p, factor=0.5, coverage=0))
        soft_fibre = week(candidates=BOOK[:3] + [rich], targets=(ENERGY, FIBRE, SODIUM))
        self.assertNotIn("lentils", choose(soft_fibre, factor=0.5, coverage=1))         # only a hard minimum is covered
        hard_energy_only = week(candidates=BOOK[:3] + [rich], targets=(ENERGY, SODIUM))     # every recipe ties on energy
        self.assertEqual(len(choose(hard_energy_only, factor=0.5, coverage=2)), 2)

    def test_one_version_of_a_recipe_its_best(self):
        v1, v2 = recipe("soup v1", 15.0, 400.0, recipe="soup"), recipe("soup v2", 14.0, 400.0, recipe="soup")
        self.assertEqual(choose(week(candidates=[v1, v2, BOOK[1]]), factor=1.0, coverage=0), {"soup v1", "rice bowl"})

    def test_a_dish_made_ahead_too_late_for_the_first_meal_still_counts(self):
        oats = recipe("oats", 15.0, 400.0, meal_types=BREAKFAST, ahead_hours=8.0)
        toast = recipe("toast", 2.0, 100.0, meal_types=BREAKFAST)
        slots = [slot("b1", when(28, 7), "Breakfast"), slot("b2", when(29, 7), "Breakfast")]
        p = week(candidates=[oats, toast], slots=slots, now=when(28, 1))
        self.assertEqual(choose(p, factor=0.5, coverage=0), {"oats"})

    def test_a_recipe_that_cannot_be_eaten_is_passed_over(self):
        untrusted = recipe("placeholder soup", 15.0, 400.0, untrusted=frozenset({"energy"}))
        breakfast = recipe("granola", 15.0, 400.0, meal_types=BREAKFAST)
        got = choose(week(candidates=[untrusted, breakfast, BOOK[1]]), factor=1.0, coverage=0)
        self.assertEqual(got, {"rice bowl"})


if __name__ == "__main__":
    unittest.main()


class ReadingTheShortlist(unittest.TestCase):
    """build_problem on the kitchen of tests/test_planning_extract.py, all dinners, a hard protein floor.
    No energy target, so the ranking is the time fit (weight 0.6, a 30-minute budget): curry and salad
    take 10 and 25 minutes, both within it, and curry comes first by name; omelette (35) and stew (60)
    rank below. Factor 0.5 over two dinners keeps one: curry. The two richest in protein, stew (25 g)
    and omelette (24 g), stay reachable. Pasta's figure is placeholder, so it cannot decide the hard
    floor and is passed over."""

    def kitchen(self):
        from tests.planning_graph import add_recipe, add_target
        from tests.test_planning_extract import kitchen
        g = kitchen()
        add_recipe(g, "stew", output_grams=500, protein_per_100g=10, provenance="estimated", yield_servings=2, minutes=60)
        add_recipe(g, "curry", output_grams=600, protein_per_100g=4, provenance="sourced", yield_servings=2, minutes=10,
                   inputs=[("Chickpeas", 300.0)])
        add_recipe(g, "salad", output_grams=200, protein_per_100g=5, provenance="sourced", yield_servings=2, minutes=25,
                   inputs=[("Lettuce", 150.0)])
        add_target(g, "protein floor", 40, 140)
        writable = WritableGraph()
        writable.nodes = g.nodes
        calculate(writable)                       # stored figures, as on the owner's instance (J28)
        return writable

    def build(self, g, **kw):
        from mealplanner.planning.extract import build_problem
        from tests.test_planning_extract import DINNERS, NOW
        kw.setdefault("shortlist_above", 2)
        kw.setdefault("shortlist_factor", 0.5)
        return build_problem(g, "week", DINNERS, NOW, **kw)

    def test_only_the_shortlist_is_read_in_full(self):
        from unittest import mock
        g = self.kitchen()
        with mock.patch.object(g, "get_all", wraps=g.get_all) as reads:
            p = self.build(g)
        self.assertEqual(set(p.candidates), {"curry", "stew", "omelette"})
        self.assertEqual(p.book_size, 5)
        self.assertIn("searched a shortlist of 3 of the 5 recipes", " ".join(p.notes))
        self.assertEqual(p.candidates["curry"].demand, {"Chickpeas": 300.0})          # read in full
        self.assertEqual(p.candidates["curry"].recipe, "recipe curry")
        read = {c.args[1] for c in reads.call_args_list if len(c.args) > 1 and c.args[1]}
        self.assertFalse({"step salad", "in0 salad", "q in0 salad"} & read)           # salad's ingredients never read
        listings = {c.args[0] for c in reads.call_args_list if len(c.args) == 1 and not c.kwargs.get("where")}
        self.assertFalse({"Specification", "QuantitySpecification", "Step"} & listings)
        whole = self.build(g, shortlist_above=None)
        self.assertEqual({cid: whole.candidates[cid] for cid in p.candidates}, p.candidates)   # each read as in full
        self.assertEqual((whole.targets, whole.slots, whole.baselines), (p.targets, p.slots, p.baselines))

    def test_a_dish_made_too_far_ahead_for_every_meal_takes_no_place(self):
        g = self.kitchen()
        g.nodes["curry"]["makeAheadHours"] = 1000.0
        self.assertEqual(set(self.build(g).candidates), {"salad", "stew", "omelette"})

    def test_two_versions_of_a_recipe_take_one_place(self):
        from tests.fakegraph import Ref
        from tests.planning_graph import add_recipe
        g = self.kitchen()
        add_recipe(g, "curry v2", output_grams=600, protein_per_100g=4, provenance="sourced", yield_servings=2, minutes=10,
                   inputs=[("Chickpeas", 300.0)])
        g.nodes["curry v2"]["specializationOf"] = Ref("recipe curry")
        calculate(g)
        p = self.build(g, shortlist_factor=1.0)
        self.assertEqual(set(p.candidates) - {"stew", "omelette"}, {"curry", "salad"})

    def test_a_recipe_a_committed_meal_cooks_is_always_read(self):
        from tests.planning_graph import add_entry
        from tests.test_planning_extract import DINNERS
        g = self.kitchen()
        add_entry(g, "lunch", "salad", DINNERS[0].start.replace(hour=12).isoformat(), servings=2)
        self.assertIn("salad", self.build(g).candidates)

    def test_an_excluded_recipe_takes_no_place(self):
        from unittest import mock
        from tests.fakegraph import Ref
        g = self.kitchen()
        g.add("ExclusionConstraint", "no chickpeas", "no chickpeas", appliesTo=Ref("Chickpeas"), strictness="hard", weight=None)
        with mock.patch.object(g, "get_all", wraps=g.get_all) as reads:
            p = self.build(g)
        self.assertEqual(set(p.candidates), {"omelette", "salad", "stew"})              # salad takes curry's place
        listings = {c.args[0] for c in reads.call_args_list if len(c.args) == 1 and not c.kwargs.get("where")}
        self.assertTrue({"Step", "Specification"} <= listings)                          # every recipe's ingredients, for it

    def test_a_soft_exclusion_counts_in_the_ranking(self):
        from tests.fakegraph import Ref
        g = self.kitchen()
        g.add("ExclusionConstraint", "few chickpeas", "few chickpeas", appliesTo=Ref("Chickpeas"), strictness="soft", weight=0.5)
        p = self.build(g)
        self.assertEqual(set(p.candidates), {"omelette", "salad", "stew"})
        self.assertEqual(p.candidates["salad"].soft_penalty, 0.0)

    def test_a_small_book_or_none_is_read_whole(self):
        g = self.kitchen()
        for kw in ({"shortlist_above": 5}, {"shortlist_above": None}):
            p = self.build(g, **kw)
            self.assertEqual((len(p.candidates), p.book_size), (5, 5))
            self.assertFalse([n for n in p.notes if "shortlist" in n])


class Widening(unittest.TestCase):
    """planning/plan.py: a shortlist that holds no week meeting every hard target is doubled."""

    def run_plan(self, sizes, feasible_at, **plan_kw):
        from types import SimpleNamespace
        from unittest import mock
        from mealplanner.planning import plan as planning
        factors, limits = [], []
        self.limits = limits

        def build(*args, **kw):
            factors.append(kw["shortlist_factor"])
            size = sizes[len(factors) - 1]
            return SimpleNamespace(candidates=dict.fromkeys(range(size)), book_size=sizes[-1], notes=[])

        def solve(problem, method, **kw):
            limits.append(kw.get("time_limit_s"))
            ok = len(problem.candidates) >= feasible_at
            return SimpleNamespace(best=SimpleNamespace(feasible=True) if ok else None)

        with mock.patch.object(planning, "build_problem", build), mock.patch.object(planning, "solve", solve), \
                mock.patch.object(planning, "diagnose", return_value="diagnosis"):
            result = planning.plan_week(None, "week", [], None, **plan_kw)
        return result, factors

    def test_doubled_until_it_holds_a_week(self):
        result, factors = self.run_plan([3, 6, 12], feasible_at=6)
        self.assertEqual(factors, [2.0, 4.0])
        self.assertTrue(result.feasible)
        self.assertEqual(result.problem.notes, ["a shortlist of 3 recipes held no week meeting every hard target, so it was doubled"])

    def test_it_stops_at_the_whole_book(self):
        result, factors = self.run_plan([3, 6], feasible_at=99)
        self.assertEqual(factors, [2.0, 4.0])
        self.assertEqual(result.diagnosis, "diagnosis")

    def test_a_shortlist_with_a_week_is_kept(self):
        result, factors = self.run_plan([3, 6], feasible_at=1)
        self.assertEqual(factors, [2.0])
        self.assertEqual(result.problem.notes, [])


class TheWholeRunsBudget(unittest.TestCase):
    """planning/plan.py: with a deadline, the search has the time left, less the reports' reserve."""

    def test_the_search_has_what_reading_leaves(self):
        from time import monotonic
        from mealplanner.planning.plan import MIN_SEARCH_S, REPORT_RESERVE_S
        runs = Widening()
        runs.run_plan([6], feasible_at=1, deadline=monotonic() + 100)
        self.assertAlmostEqual(runs.limits[0], 100 - REPORT_RESERVE_S, delta=1)
        result, _ = runs.run_plan([6], feasible_at=1, deadline=monotonic() + 20)
        self.assertEqual(runs.limits, [MIN_SEARCH_S])
        self.assertIn("the search had only 10 s", " ".join(result.problem.notes))
        result, _ = runs.run_plan([6], feasible_at=1, time_limit_s=45.0)
        self.assertEqual(runs.limits, [45.0])
        self.assertEqual(result.problem.notes, [])

    def test_a_doubled_shortlist_has_what_is_left_then(self):
        from time import monotonic
        runs = Widening()
        runs.run_plan([3, 6], feasible_at=6, deadline=monotonic() + 100)
        self.assertEqual(len(runs.limits), 2)
        self.assertGreaterEqual(runs.limits[0], runs.limits[1])
