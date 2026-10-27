"""mealplanner/planning/contract.py: the planner's JSON contract (docs/architecture-decision.md §7a,
stage 4). A problem must come back from JSON as the same problem, searched to the same plan, and a
plan must come back as the same picks; a field added to the problem must not be left out of it."""

import dataclasses
import json
import unittest
from datetime import timedelta, timezone

from mealplanner.planning.contract import (FORMAT, ContractError, picks_from_json, plan_to_json, problem_from_json,
                                           problem_to_json)
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.model import Fixed, Lot, PlanningProblem, PrepSession, Request, Target, Weights
from mealplanner.planning.search import oracle
from tests.planning_fixtures import cand, problem, slot, when
from tests.test_planning_search import SEEDS, random_problem


def through_json(p: PlanningProblem) -> PlanningProblem:
    return problem_from_json(json.loads(json.dumps(problem_to_json(p))))


def everything() -> PlanningProblem:
    """A problem in which every field, and every field of what it holds, differs from its default."""
    jamie, alex = "p-jamie", "p-alex"
    soup = cand("soup", 20, 30, meal_types=frozenset({"Dinner", "Lunch"}), difficulty="medium", yield_servings=4.0,
                untrusted=frozenset({"protein"}), demand={"chicken": 400.0}, soft_penalty=0.2, leftover_days=3.0,
                uses=(when(20, 18),), recipe="r-soup", ahead_hours=2.0)
    oats = cand("oats", 10, 5, meal_types=frozenset({"Breakfast"}), hard_excluded=True, recipe="r-oats")
    toast = cand("toast", 6, 5, meal_types=frozenset({"Breakfast"}))
    eastern = timezone(timedelta(hours=-4))
    slots = [slot("Mon Breakfast", when(28, 8).astimezone(eastern), "Breakfast",
                  Fixed(eaten=1.5, candidate="toast", cooked=2.0, name="toast, eaten", entry_id="e1", shares=((jamie, 1.0), (alex, 0.5)))),
             slot("Mon Brunch", when(28, 10), "Breakfast", Fixed(source=0, name="toast, again")),
             slot("Mon Lunch", when(28, 12), "Lunch", eaters=(jamie,)),
             slot("Mon Dinner", when(28, 18), "Dinner")]
    return PlanningProblem(
        slots=tuple(slots), candidates={c.id: c for c in (soup, oats, toast)},
        targets=(Target("protein", "protein", "daily", 50.0, 150.0, True, 0.5, "Protein", "midnight America/Edmonton", jamie),),
        lots=(Lot("chicken", 500.0, when(30, 12), "chicken breast"),),
        weights=Weights(0.6, 0.3, 0.2, 0.1, 45.0, 2.0, 1.5),
        now=when(27, 9), max_difficulty="medium", servings_eaten=1.5, notes=["a note"],
        baseline={"protein": 5.0}, units={"protein": "g"}, portions=(1.0, 1.5),
        eaters=(jamie, alex), eater_portions={jamie: (1.0, 2.0)}, baselines={jamie: {"protein": 10.0, "fibre": None}},
        eater_names={jamie: "Jamie", alex: "Alex"}, book_size=40,
        requests=(Request("soup", frozenset({"soup"}), 3),),
        preps=(PrepSession("Sun prep", when(27, 14), 120.0, 3),),
        repeat_tolerance=2)


class TheProblem(unittest.TestCase):
    def test_random_problems_come_back_the_same(self):
        for seed in SEEDS:
            p = random_problem(seed)
            self.assertEqual(through_json(p), p, seed)

    def test_every_field_is_carried(self):
        """A field the contract left out would come back as its default; here none is at its default."""
        p = everything()
        for f in dataclasses.fields(PlanningProblem):
            if f.name == "_cache":
                continue
            default = f.default if f.default is not dataclasses.MISSING else (f.default_factory() if f.default_factory is not dataclasses.MISSING else None)
            self.assertNotEqual(getattr(p, f.name), default, f"everything() leaves {f.name} at its default")
        held = [*p.slots, *(s.fixed for s in p.slots if s.fixed), *p.candidates.values(), *p.targets, *p.lots, p.weights,
                *p.requests, *p.preps]
        for kind in {type(h) for h in held}:
            of_kind = [h for h in held if type(h) is kind]
            for f in dataclasses.fields(kind):
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                    continue
                default = f.default if f.default is not dataclasses.MISSING else f.default_factory()
                self.assertTrue(any(getattr(h, f.name) != default for h in of_kind),
                                f"everything() leaves {kind.__name__}.{f.name} at its default everywhere")
        self.assertEqual(through_json(p), p)

    def test_times_keep_their_offset_and_candidates_their_order(self):
        p = everything()
        back = through_json(p)
        self.assertEqual(back.slots[0].start.utcoffset(), timedelta(hours=-4))
        self.assertEqual(list(back.candidates), list(p.candidates))

    def test_it_is_plain_json(self):
        text = json.dumps(problem_to_json(everything()))           # no default= needed
        self.assertIn('"format": %d' % FORMAT, text)

    def test_what_is_refused(self):
        data = problem_to_json(everything())
        with self.assertRaises(ContractError):
            problem_from_json({**data, "format": FORMAT + 1})
        data["now"] = "2026-09-27T09:00:00"                       # no offset
        with self.assertRaises(ContractError):
            problem_from_json(data)
        bad = problem_to_json(everything())
        bad["requests"][0]["candidates"] = ["no such recipe"]
        with self.assertRaises(ValueError):                        # checked as any problem is
            problem_from_json(bad)


class ThePlan(unittest.TestCase):
    def test_the_search_finds_the_same_plan_and_the_plan_comes_back_as_its_picks(self):
        searched = 0
        for seed in SEEDS:
            p = random_problem(seed)
            q = through_json(p)
            want, got = oracle(p).best, oracle(q).best
            self.assertEqual(want is None, got is None, seed)
            if want is None:
                continue
            searched += 1
            self.assertEqual(got.picks, want.picks, seed)
            self.assertAlmostEqual(got.objective, want.objective, msg=seed)
            sent = json.loads(json.dumps(plan_to_json(q, got.picks, objective=got.objective, legal=got.legal, proven=True,
                                                      method="oracle")))
            self.assertEqual(picks_from_json(q, sent), tuple(got.picks), seed)
            self.assertAlmostEqual(evaluate(q, picks_from_json(q, sent)).objective, want.objective, msg=seed)
        self.assertGreater(searched, 40)

    def test_a_plan_names_slots_and_prep_sessions_by_key(self):
        p = problem([slot("a", when(28, 12)), slot("b", when(28, 18)), slot("c", when(29, 18))],
                    [cand("stew", 30, 60, yield_servings=4.0, leftover_days=3.0)],
                    preps=(PrepSession("Sun prep", when(27, 14), 120.0, 2),), now=when(26, 9))
        from mealplanner.planning.model import Pick
        picks = (Pick(candidate="stew", prep=0, portion=1.0), Pick(source=0), Pick(source=0))
        sent = plan_to_json(p, picks, objective=1.0, legal=True, proven=False, method="hand")
        self.assertEqual([(c["slot"], c["candidate"], c["leftovers_of"], c["prep"]) for c in sent["picks"]],
                         [("a", "stew", None, "Sun prep"), ("b", None, "a", None), ("c", None, "a", None)])
        self.assertEqual(picks_from_json(p, sent), picks)

    def test_a_plan_for_another_problem_is_refused(self):
        p, other = random_problem(1), random_problem(2)
        best = oracle(p).best
        sent = plan_to_json(p, best.picks, objective=best.objective, legal=best.legal, proven=True, method="oracle")
        if [s.key for s in other.slots] != [s.key for s in p.slots]:
            with self.assertRaises(ContractError):
                picks_from_json(other, sent)
        with self.assertRaises(ContractError):
            picks_from_json(p, {**sent, "format": FORMAT + 1})


if __name__ == "__main__":
    unittest.main()


class TheWorker(unittest.TestCase):
    """tools/plan_problem.py: a problem file in, a plan file out, as plan_week would plan it."""

    def setUp(self):
        import importlib.util
        import os
        import tempfile
        spec = importlib.util.spec_from_file_location("plan_problem_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "plan_problem.py"))
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def run_tool(self, p, *argv):
        import io
        import os
        from contextlib import redirect_stdout
        path = os.path.join(self.dir.name, "week.problem.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(problem_to_json(p), fh)
        with redirect_stdout(io.StringIO()):
            code = self.tool.main([path, "--method", "oracle", *argv])
        with open(os.path.join(self.dir.name, "week.plan.json"), encoding="utf-8") as fh:
            return code, json.load(fh)

    def test_its_plan_is_the_searchs_and_comes_back_as_picks(self):
        planned = 0
        for seed in list(SEEDS)[:30]:
            p = random_problem(seed)
            code, sent = self.run_tool(p)
            want = oracle(p).best
            if want is not None and want.feasible:
                planned += 1
                self.assertEqual(code, 0, seed)
                self.assertAlmostEqual(sent["objective"], want.objective, msg=seed)
                self.assertAlmostEqual(evaluate(p, picks_from_json(p, sent)).objective, want.objective, msg=seed)
                self.assertIn("Plan (", sent["report"])
        self.assertGreater(planned, 10)

    def test_a_week_with_no_plan_says_why(self):
        p = problem([slot("a", when(28, 18))], [cand("thin soup", 5, 20)],
                    [Target("protein", "protein", "per_meal", 60.0, None, True, 0.0, "Protein")])
        code, sent = self.run_tool(p)
        self.assertEqual((code, sent["picks"]), (1, None))
        self.assertIn("No plan meets every hard constraint", sent["report"])


class BuiltOnly(unittest.TestCase):
    def test_plan_week_can_stop_at_the_problem_extract_builds(self):
        from mealplanner.planning.extract import build_problem
        from mealplanner.planning.plan import plan_week
        from tests.test_planning_extract import DINNERS, NOW, kitchen
        built = plan_week(kitchen(), "week", DINNERS, NOW, build_only=True)
        self.assertIsNone(built.evaluation)
        self.assertEqual(built.search.method, "not searched")
        self.assertEqual(built.problem, build_problem(kitchen(), "week", DINNERS, NOW))
        self.assertEqual(through_json(built.problem), built.problem)
