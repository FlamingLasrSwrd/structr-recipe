"""What a week's purchases leave to spoil, weighed by the planner (Weights.package_waste; docs/packages.md
stage 4; docs/optimizer-design.md Sec 12, "Package waste").

Worked out by hand. Tomatoes come in a 411 g can. Chili uses 400 g for 4 servings, 100 g a serving.
The week is Mon 18:00 and Wed 18:00 (days 28 and 30); its last meal, Wed 18:00, is when what is left
waits for next week.
  - Chili on Mon alone: one can, 311 g left. Kept 1 day once opened, it is past keeping Tue 18:00,
    before the last meal: all of it counts, 311 / 411 = 0.7567 of a can.
  - Chili on Mon and Wed, kept 1 day: Wed is past what Mon's can keeps, so two cans, each 311 g left.
    Mon's counts in full; Wed's keeps to Thu 18:00, a day past the last meal, so 6/7 of it:
    311/411 x (1 + 6/7) = 1.4053.
  - Kept 3 days: Wed is within Mon's can, so one can for 200 g, 211 g left, keeping to Thu 18:00 (Mon
    + 3 days), a day past the last meal: 211/411 x 6/7 = 0.4400.
  - Stock of 50 g good past the week: Mon needs 50 g more, a can, 361 g left: 361/411.
  - Sizes 411 g and 794 g, 850 g needed: one of each (packages.choose; docs/packages.md), 355 g left,
    counted in the smallest size: 355/411.
The best week: soup and pasta each use half of a 794 g can, rice and salad none; pasta takes 40
minutes against a 30 minute budget (time fit 2/3), the rest 20. Without the term the best week is
soup, rice and salad: 3 x 0.6 time + 3 x 0.5 variety = 3.3, and soup leaves half a can. Weighed at
1, soup on Mon leaves 397 g past keeping by Wed (kept 2 days): -0.5, so 2.8; soup on Wed keeps 2
days past the last meal, 5/7 of half a can: 3.3 - 0.357 = 2.943; soup and pasta sharing one can
within 2 days leave nothing: 0.6 x (1 + 1 + 2/3) + 1.5 = 3.1, the best.
"""

import random
import unittest
from dataclasses import replace

from mealplanner.planning import cpsat
from mealplanner.planning.evaluate import evaluate, initial_partial, options, prefix_bound
from mealplanner.planning.extract import PackageLevelError, _packaging, build_problem
from mealplanner.planning.plan import plan_week
from mealplanner.planning.model import Fixed, Lot, Packaging, Pick, Weights
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import auto, beam, exact, improve, oracle
from tests.fakegraph import Ref
from tests.planning_fixtures import cand, problem, slot, when
from tests.test_planning_search import SEEDS, random_problem

CHILI = cand("chili", None, 20, demand={"tomato": 400.0}, yield_servings=4.0)
SALAD = cand("salad", None, 20)
CAN = 411.0


def week(keeps=1.0, sizes=(CAN,), weight=1.0, candidates=(CHILI, SALAD), **kw):
    return problem([slot("Mon", when(28, 18)), slot("Wed", when(30, 18))], candidates,
                   weights=Weights(time=0.0, variety=0.0, package_waste=weight),
                   packaging=(Packaging("tomato", tuple(sizes), keeps, "Tomatoes"),), **kw)


def cooks(*names):
    return tuple(Pick(candidate=n) for n in names)


class TheTerm(unittest.TestCase):
    def test_what_one_purchase_leaves_past_keeping_counts_in_full(self):
        ev = evaluate(week(), cooks("chili", "salad"))
        self.assertAlmostEqual(ev.terms["package_waste"], -311 / 411)
        (lo,) = ev.package_leftovers
        self.assertEqual((lo.bought, lo.left, lo.opened, lo.expires, lo.share), (411.0, 311.0, when(28, 18), when(29, 18), 1.0))

    def test_a_use_past_what_the_open_package_keeps_buys_another(self):
        ev = evaluate(week(), cooks("chili", "chili"))
        self.assertAlmostEqual(ev.terms["package_waste"], -311 / 411 * (1 + 6 / 7))
        self.assertEqual([(lo.opened, lo.left) for lo in ev.package_leftovers], [(when(28, 18), 311.0), (when(30, 18), 311.0)])

    def test_uses_while_it_keeps_share_one_purchase(self):
        ev = evaluate(week(keeps=3.0), cooks("chili", "chili"))
        self.assertAlmostEqual(ev.terms["package_waste"], -211 / 411 * 6 / 7)
        self.assertEqual([lo.bought for lo in ev.package_leftovers], [411.0])

    def test_a_use_on_the_day_it_stops_keeping_still_shares_it(self):
        """As a cooked dish's leftovers do (evaluate.leftover_reason): past keeping only after its time."""
        self.assertEqual([lo.bought for lo in evaluate(week(keeps=2.0), cooks("chili", "chili")).package_leftovers], [411.0])

    def test_the_weight_scales_it(self):
        self.assertAlmostEqual(evaluate(week(weight=2.5), cooks("chili", "salad")).terms["package_waste"], -2.5 * 311 / 411)

    def test_stock_is_used_first(self):
        lots = (Lot("tomato", 50.0, when(40, 12)),)
        ev = evaluate(week(lots=lots), cooks("chili", "salad"))
        self.assertAlmostEqual(ev.terms["package_waste"], -361 / 411)
        enough = (Lot("tomato", 100.0, when(40, 12)),)
        self.assertEqual(evaluate(week(lots=enough), cooks("chili", "salad")).package_leftovers, [])

    def test_whole_packages_of_several_sizes_counted_in_the_smallest(self):
        big = cand("big chili", None, 20, demand={"tomato": 850.0})
        ev = evaluate(week(sizes=(CAN, 794.0), candidates=(big, SALAD)), cooks("big chili", "salad"))
        (lo,) = ev.package_leftovers
        self.assertAlmostEqual(lo.bought, 1205.0)
        self.assertAlmostEqual(ev.terms["package_waste"], -355 / 411)

    def test_what_keeps_a_week_past_the_last_meal_costs_nothing(self):
        ev = evaluate(week(keeps=9.0), cooks("salad", "chili"))      # Wed + 9 days: 9 days past the last meal
        self.assertEqual(ev.terms["package_waste"], 0.0)
        self.assertEqual(len(ev.package_leftovers), 1)
        self.assertEqual(ev.package_leftovers[0].share, 0.0)

    def test_with_no_keeping_time_known_nothing_is_counted(self):
        ev = evaluate(week(keeps=None), cooks("chili", "chili"))
        self.assertEqual(ev.terms["package_waste"], 0.0)
        self.assertEqual([(lo.bought, lo.left, lo.expires) for lo in ev.package_leftovers], [(411.0, 211.0, None)])

    def test_a_cook_already_past_was_bought_for(self):
        p = problem([slot("Sun", when(27, 18), fixed=Fixed(candidate="chili", cooked=1.0)), slot("Mon", when(28, 18)),
                     slot("Wed", when(30, 18))], (CHILI, SALAD), weights=Weights(time=0.0, variety=0.0, package_waste=1.0),
                    packaging=(Packaging("tomato", (CAN,), 1.0, "Tomatoes"),), now=when(28, 9))
        self.assertEqual(evaluate(p, (Pick(candidate="chili"),) + cooks("salad", "salad")).package_leftovers, [])
        self.assertAlmostEqual(evaluate(p, (Pick(candidate="chili"),) + cooks("chili", "salad")).terms["package_waste"], -311 / 411)

    def test_at_zero_or_without_packaging_it_is_not_there(self):
        for p in (week(weight=0.0), replace(week(), packaging=(), _cache={})):
            ev = evaluate(p, cooks("chili", "salad"))
            self.assertNotIn("package_waste", ev.terms)
            self.assertEqual(ev.package_leftovers, [])

    def test_weighed_it_changes_nothing_else(self):
        for lots in ((), (Lot("tomato", 50.0, when(40, 12)),)):
            on, off = (evaluate(week(weight=w, lots=lots), cooks("chili", "salad")) for w in (1.0, 0.0))
            self.assertEqual(on.slot_details, off.slot_details, lots)
            self.assertEqual({k: v for k, v in on.terms.items() if k != "package_waste"}, off.terms, lots)

    def test_what_is_refused(self):
        for bad in (dict(weight=-1.0), dict(sizes=()), dict(sizes=(0.0,)), dict(keeps=-1.0)):
            with self.assertRaises(ValueError, msg=bad):
                week(**bad)
        with self.assertRaises(ValueError):
            replace(week(), packaging=(Packaging("tomato", (CAN,)), Packaging("tomato", (CAN,))))

    def test_the_report_says_what_spoils(self):
        p = week()
        text = describe_plan(p, evaluate(p, cooks("chili", "salad")))
        self.assertIn("package waste: 0.76 package(s)' worth left to spoil, at 1 a point each:", text)
        self.assertIn("Tomatoes: 311 g left of 411 g bought Mon, keeps to Tue 29 Sep (all of it): 0.76", text)
        self.assertIn("package_waste -0.757", text)


def sharing_week(weight):
    return problem([slot("Mon", when(28, 18)), slot("Tue", when(29, 18)), slot("Wed", when(30, 18))],
                   [cand("soup", None, 20, demand={"tomato": 397.0}), cand("pasta", None, 40, demand={"tomato": 397.0}),
                    cand("rice", None, 20), cand("salad", None, 20)],
                   weights=Weights(time=0.6, variety=0.5, time_budget_minutes=30.0, package_waste=weight),
                   packaging=(Packaging("tomato", (794.0,), 2.0, "Tomatoes"),))


class TheBestWeek(unittest.TestCase):
    def test_unweighed_half_a_can_is_left_and_weighed_two_recipes_share_it(self):
        light = oracle(sharing_week(0.0)).best
        self.assertAlmostEqual(light.objective, 3.3)
        self.assertEqual(sorted(x.candidate for x in light.picks), ["rice", "salad", "soup"])
        p = sharing_week(1.0)
        self.assertAlmostEqual(evaluate(p, cooks("soup", "rice", "salad")).objective, 2.8)   # half a can thrown out
        self.assertAlmostEqual(evaluate(p, cooks("rice", "salad", "soup")).objective, 3.3 - 0.5 * 5 / 7)
        heavy = oracle(p).best
        self.assertAlmostEqual(heavy.objective, 3.1)
        self.assertEqual(sorted(x.candidate for x in heavy.picks), ["pasta", "rice", "soup"])
        self.assertEqual(heavy.terms["package_waste"], 0.0)

    def test_every_search_finds_it(self):
        p = sharing_week(1.0)
        for result in (exact(p), beam(p), auto(p, time_limit_s=2), improve(p, evaluate(p, oracle(sharing_week(0.0)).best.picks))):
            self.assertAlmostEqual(result.best.objective, 3.1, msg=result.method)

    @unittest.skipUnless(cpsat.available(), "OR-tools is not installed")
    def test_cpsat_uses_the_terms_ceiling_and_does_not_claim_a_proof_it_lacks(self):
        """CP-SAT does not model package waste (a step in what is bought); it takes its ceiling, 0, and
        the plan it finds is re-scored by evaluate(), so it claims a proof only when the two agree."""
        p = sharing_week(1.0)
        result = cpsat.solve(p, time_limit_s=5)
        self.assertGreaterEqual(result.upper_bound, 3.1 - 1e-6)
        if result.best.objective < result.upper_bound - 1e-4:
            self.assertFalse(result.proven)


def with_packaging(seed: int):
    """A random problem (tests/test_planning_search.py) whose pool is bought in packages."""
    rnd = random.Random(1000 + seed)
    p = random_problem(seed)
    return replace(p, packaging=(Packaging("p", tuple(rnd.sample([150.0, 250.0, 450.0], rnd.randint(1, 2))),
                                           rnd.choice([None, 0.5, 1.0, 3.0]), "pool p"),),
                   weights=replace(p.weights, package_waste=rnd.choice([0.5, 1.0, 2.0])), _cache={})


class AgainstTheOracle(unittest.TestCase):
    def test_the_bound_never_falls_below_what_a_week_comes_to(self):
        checked = 0
        for seed in SEEDS:
            p = with_packaging(seed)
            rng = random.Random(seed)
            open_slots = p.open_slots()
            for _ in range(20):
                partial = initial_partial(p)
                stuck = False
                for i in open_slots:
                    choices = options(p, partial, i)
                    if not choices:
                        stuck = True
                        break
                    partial[i] = rng.choice(choices)
                if stuck:
                    continue
                final = evaluate(p, partial)
                if not final.legal:
                    continue
                checked += 1
                for k in range(len(open_slots) + 1):
                    prefix = list(partial)
                    for i in open_slots[k:]:
                        prefix[i] = None
                    self.assertGreaterEqual(prefix_bound(p, prefix).objective, final.objective - 1e-9, seed)
        self.assertGreater(checked, 200)

    def test_the_exact_search_still_finds_the_best_week(self):
        weighed = 0
        for seed in SEEDS:
            p = with_packaging(seed)
            want, got = oracle(p), exact(p)
            self.assertTrue(got.proven, seed)
            self.assertEqual(want.best is None, got.best is None, seed)
            if want.best:
                self.assertAlmostEqual(want.best.objective, got.best.objective, delta=1e-6, msg=f"seed {seed}")
                weighed += want.best.terms.get("package_waste", 0.0) < 0
        self.assertGreater(weighed, 5)          # the term did decide something


class ReadFromTheGraph(unittest.TestCase):
    """extract._packaging: the sizes the shopping list would buy, in grams, and how long each keeps
    once opened. Eggs are sold in a 600 g box and a 300 g half box ("box" before "half box", the order
    package_table reads them), and keep 3 days in the fridge once opened; Noodles come in a 340 g bag
    and have no opened figure, so they keep as they do unopened in the pantry, 730 days; Salt is sold
    in no package."""

    def graph(self):
        from tests.test_packages import shelf
        from tests.planning_graph import add_type, new_kitchen
        g = new_kitchen()
        for name in ("Eggs", "Noodles", "Salt", "ShelfLife", "Fridge", "Pantry", "Freezer", "Opened", "Sealed",
                     "PurchaseQuantity"):
            add_type(g, name)
        g.add("TypeHierarchy", "Package Reference", "Package Reference")
        g.add("DomainType", "US supermarket", "US supermarket", hierarchy=Ref("Package Reference"), parent=None,
              defaultSpecifications=[], children=[])
        for food, label, grams in (("Eggs", "half box", 300.0), ("Eggs", "box", 600.0), ("Noodles", "bag", 340.0)):
            name = f"US supermarket -- {food} -- {label}"
            g.add("QuantitySpecification", f"{name} size", value=grams, unit="g")
            g.add("DefaultSpecification", name, name, forType=Ref("US supermarket"), hasKind=Ref("PurchaseQuantity"),
                  keyedBy=[Ref(food)], hasValue=Ref(f"{name} size"), provenance="estimated")
            g.nodes["US supermarket"]["defaultSpecifications"].append(Ref(name))
        shelf(g, "Eggs", 21, "Fridge")
        shelf(g, "Eggs", 3, "Fridge", "Opened")
        shelf(g, "Noodles", 730, "Pantry")
        return g

    def test_sizes_and_keeping_times(self):
        notes = []
        got = _packaging(self.graph(), ["Eggs", "Noodles", "Salt"], None, notes)
        self.assertEqual(got, (Packaging("Eggs", (600.0, 300.0), 3.0, "Eggs"), Packaging("Noodles", (340.0,), 730.0, "Noodles")))
        self.assertEqual(notes, ["package waste weighed: 2 of the 3 foods the recipes use are sold in packages at 'US supermarket'"])

    def test_the_week_reads_it_only_when_weighed_and_plans_with_it(self):
        from tests.planning_graph import add_recipe
        from tests.test_planning_extract import DINNERS, NOW
        g = self.graph()
        add_recipe(g, "omelette", output_grams=400, protein_per_100g=12, provenance="sourced", yield_servings=2, minutes=35,
                   inputs=[("Eggs", 300.0)])
        add_recipe(g, "pasta", output_grams=300, protein_per_100g=8, provenance="sourced", yield_servings=2, minutes=20,
                   inputs=[("Noodles", 200.0), ("Eggs", 100.0)])
        self.assertEqual(build_problem(g, "week", DINNERS, NOW).packaging, ())
        p = build_problem(g, "week", DINNERS, NOW, package_waste=1.5)
        self.assertEqual(p.weights.package_waste, 1.5)
        self.assertEqual([pk.pool for pk in p.packaging], ["Eggs", "Noodles"])
        result = plan_week(g, "week", DINNERS, NOW, method="oracle", package_waste=1.5)
        self.assertIn("package waste:", result.text())
        with self.assertRaises(PackageLevelError):
            build_problem(g, "week", DINNERS, NOW, package_waste=1.0, package_level="No such level")

    def test_no_level_loaded_is_noted(self):
        from tests.planning_graph import new_kitchen
        notes = []
        self.assertEqual(_packaging(new_kitchen(), ["Eggs"], None, notes), ())
        self.assertIn("no package level is loaded", notes[0])


class TheWeekFile(unittest.TestCase):
    def test_read_from_the_weights_and_checked(self):
        from tests.test_plan_week_tool import WEEK, read, tool
        week = read(WEEK + 'packages = "Home packages"\n[weights]\npackage_waste = 1.5\n')
        self.assertEqual((week["weights"]["package_waste"], week["packages"]), (1.5, "Home packages"))
        for bad in ("-1", '"lots"', "true"):
            with self.assertRaises(tool.WeekError) as caught:
                read(WEEK + f"[weights]\npackage_waste = {bad}\n")
            self.assertIn("package_waste is points off per package's worth", " ".join(caught.exception.args[0]))
        with self.assertRaises(tool.WeekError):
            read(WEEK + "packages = 3\n")


if __name__ == "__main__":
    unittest.main()
