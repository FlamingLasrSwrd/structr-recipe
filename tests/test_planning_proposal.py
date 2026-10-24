"""A proposed week kept and committed as proposed (planning/proposal.py, plan_week(proposal=...),
tools/plan_week.py --commit)."""

import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick
from mealplanner.planning.plan import plan_week
from mealplanner.planning.proposal import ProposalError, picks_from, to_data
from tests.fakegraph import when
from tests.planning_fixtures import cand, problem, slot
from tests.planning_fixtures import when as day
from tests.planning_graph import add_target
from tests.test_planning_extract import NOW, kitchen

MON, TUE = SlotSpec(when(28, 18), "Dinner", "Mon dinner"), SlotSpec(when(29, 18), "Dinner", "Tue dinner")


def household():
    stew = cand("stew", 20, 30, leftover_days=3.0, yield_servings=4.0)
    return problem([slot("Mon dinner", day(28, 18)), slot("Tue dinner", day(29, 18))], (stew, cand("salad", 10, 10)),
                   eaters=("a", "b"), eater_portions={"a": (1.0, 1.5), "b": (0.5, 1.0)}, eater_names={"a": "Ari", "b": "Bo"})


class KeptAndReadBack(unittest.TestCase):
    def test_a_week_reads_back_as_the_same_picks(self):
        p = household()
        picks = (Pick(candidate="stew", shares=(1.5, 0.5)), Pick(source=0, shares=(1.0, 1.0)))
        data = to_data(p, evaluate(p, picks), "2026-09-28")
        self.assertEqual(data["meals"], [{"slot": "Mon dinner", "cook": "stew", "shares": {"Ari": 1.5, "Bo": 0.5}},
                                         {"slot": "Tue dinner", "leftover_of": "Mon dinner", "shares": {"Ari": 1.0, "Bo": 1.0}}])
        self.assertEqual(picks_from(p, json.loads(json.dumps(data))), picks)

    def test_what_no_longer_fits_is_named_and_refused(self):
        p = household()
        data = to_data(p, evaluate(p, (Pick(candidate="stew", shares=(1.0, 1.0)), Pick(candidate="salad", shares=(1.0, 1.0)))),
                       "2026-09-28")
        for change, said in (
                (lambda d: d["meals"][1].update(cook="soup"), "'soup' is not in the recipe book"),
                (lambda d: d["meals"][0].update(shares={"Ari": 1.0}), "eaten by ['Ari']"),
                (lambda d: d["meals"][0].update(slot="Wed dinner"), "Wed dinner: no longer an open meal"),
                (lambda d: d["meals"].pop(), "not in the proposal: Tue dinner"),
                (lambda d: d.update(format=0), "format 0")):
            changed = json.loads(json.dumps(data))
            change(changed)
            with self.assertRaises(ProposalError) as caught:
                picks_from(p, changed)
            self.assertIn(said, str(caught.exception))


class ReadAndRecord:
    """The kitchen graph to read, and a record of what committing would write."""

    def __init__(self, g):
        self.g, self.writes = g, []

    def __getattr__(self, name):
        return getattr(self.g, name)

    def upsert(self, type_name, key, value, fields):
        self.writes.append((type_name, value, dict(fields)))
        return f"{type_name}:{value}"


class CommittingTheKeptWeek(unittest.TestCase):
    def kept(self, picks):
        p = build_problem(kitchen(), "week", [MON, TUE], NOW, leftover_days=3.0)
        return to_data(p, evaluate(p, picks), "2026-09-28")

    def test_the_kept_week_is_written_without_searching_again(self):
        data = self.kept((Pick(candidate="pasta"), Pick(candidate="omelette")))      # not what a search would choose
        client = ReadAndRecord(kitchen())
        with mock.patch("mealplanner.planning.plan.solve") as search:
            result = plan_week(client, "week", [MON, TUE], NOW, leftover_days=3.0, commit=True, proposal=data)
        search.assert_not_called()
        written = [w[1] for w in client.writes if w[0] == "MealPlanEntry"]
        self.assertEqual(written, ["Mon dinner -- pasta", "Tue dinner -- omelette"])
        self.assertIn("the saved proposal, checked against the graph again", result.text())

    def test_a_kept_week_that_now_misses_a_hard_target_is_not_written(self):
        data = self.kept((Pick(candidate="pasta"), Pick(candidate="pasta")))
        g = kitchen()
        add_target(g, "floor", 20, None)                     # pasta's figure is placeholder: it cannot meet a hard target
        client = ReadAndRecord(g)
        with self.assertRaises(ProposalError):
            plan_week(client, "week", [MON, TUE], NOW, leftover_days=3.0, commit=True, proposal=data)
        self.assertEqual(client.writes, [])


class TheTool(unittest.TestCase):
    tool = None

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("plan_week_tool_p", os.path.join(os.path.dirname(__file__), "..", "tools", "plan_week.py"))
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def run_tool(self, folder, argv, given):
        week = os.path.join(folder, "week.toml")
        with open(week, "w") as fh:
            fh.write('start = 2026-10-26\ndays = 1\nmeals = [{ type = "Dinner", at = "18:30" }]\n')

        def fake_plan(*args, **kw):
            given.update(kw)
            return SimpleNamespace(text=lambda: "", evaluation=SimpleNamespace(), problem=None, committed=[1, 2])

        with mock.patch.object(self.tool, "connect", return_value=SimpleNamespace(wait_until_ready=lambda: None)), \
                mock.patch.object(self.tool, "ensure_week", return_value="week"), \
                mock.patch.object(self.tool, "template", return_value=[]), \
                mock.patch.object(self.tool, "plan_week", fake_plan), mock.patch.object(self.tool, "history", return_value=""), \
                mock.patch.object(self.tool, "describe_nutrients", return_value=""), \
                mock.patch.object(self.tool, "to_data", return_value={"format": 1, "week": "2026-10-26", "meals": []}), \
                mock.patch("builtins.print"):
            return self.tool.main([week, *argv]), os.path.join(folder, "week.proposal.json")

    def test_a_proposal_is_kept_then_committed_as_kept_then_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            given = {}
            code, kept = self.run_tool(folder, [], given)
            self.assertEqual((code, given["proposal"], given["commit"]), (0, None, False))
            self.assertTrue(os.path.exists(kept))
            given.clear()
            code, kept = self.run_tool(folder, ["--commit"], given)
            self.assertEqual((code, given["proposal"]["week"], given["commit"]), (0, "2026-10-26", True))
            self.assertFalse(os.path.exists(kept))

    def test_fresh_or_another_weeks_proposal_is_not_committed(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "week.proposal.json"), "w") as fh:
                json.dump({"format": 1, "week": "2026-10-26", "meals": []}, fh)
            given = {}
            self.run_tool(folder, ["--commit", "--fresh"], given)
            self.assertIsNone(given["proposal"])
            with open(os.path.join(folder, "week.proposal.json"), "w") as fh:
                json.dump({"format": 1, "week": "2026-10-05", "meals": []}, fh)
            given.clear()
            code, _ = self.run_tool(folder, ["--commit"], given)
            self.assertEqual((code, given), (1, {}))


if __name__ == "__main__":
    unittest.main()
