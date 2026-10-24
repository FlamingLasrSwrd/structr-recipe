"""Meal-prep sessions read in, written out and reported (docs/optimizer-design.md Sec 12): the week file,
build_problem, commit_plan, the kept proposal, and the nutrition report.

The kitchen is tests/test_planning_extract.py's: an omelette (35 minutes, yield 2) and pasta. A
session on Monday at 10:00 makes the omelette for Monday's and Tuesday's dinners; cooked food keeps
3 days from the session.
"""

import unittest

from mealplanner.nutrition_scope import nutrition_report
from mealplanner.planning.commit import commit_plan
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick, PrepSession
from mealplanner.planning.proposal import picks_from, to_data
from mealplanner.planning.report import describe_plan
from tests.fakegraph import Ref, at, when
from tests.planning_graph import Recorder, add_entry, add_target
from tests.test_plan_week_tool import WEEK, read, tool
from tests.test_planning_extract import NOW, kitchen

SESSION = PrepSession("Mon 28 Sep Prep", when(28, 10), 60.0, 1)
DINNERS = [SlotSpec(when(28, 18), "Dinner", "Mon dinner"), SlotSpec(when(29, 18), "Dinner", "Tue dinner")]


def made_ahead(g=None, **kw):
    problem = build_problem(g or kitchen(), "week", DINNERS, NOW, leftover_days=3, preps=(SESSION,), **kw)
    return problem, evaluate(problem, (Pick(candidate="omelette", prep=0), Pick(source=0)))


class Read(unittest.TestCase):
    def test_the_week_files_sessions_the_day_before_a_monday_start_included(self):
        week = read(WEEK + 'prep = [{ at = "Sun 14:00", minutes = 120 }]\n')
        sessions = week["preps"]
        self.assertEqual([(s.key, s.minutes, s.dishes) for s in sessions], [("Sun 04 Oct Prep", 120.0, 2)])
        week = read(WEEK + 'prep = [{ at = "Tue 17:00", minutes = 60, dishes = 1 }]\n')     # two days: Sun 4 to Tue 6
        self.assertEqual(week["preps"][0].start.isoformat(), "2026-10-06T17:00:00-06:00")

    def test_what_a_session_cannot_be(self):
        for bad, why in (('{ at = "Funday 14:00", minutes = 60 }', "not a weekday"),
                         ('{ at = "Wed 14:00", minutes = 60 }', "not a weekday of this week"),   # Sun 4 to Tue 6
                         ('{ at = "Sun", minutes = 60 }', "a weekday and a time"),
                         ('{ at = "Sun 14:00", minutes = 0 }', "working time"),
                         ('{ at = "Sun 14:00", minutes = 60, dishes = 0 }', "how many dishes")):
            with self.assertRaises(tool.WeekError) as caught:
                read(WEEK + f"prep = [{bad}]\n")
            self.assertIn(why, " ".join(caught.exception.args[0]))

    def test_the_recipes_asked_for(self):
        week = read(WEEK + 'cook = ["Stew", { recipe = "Curry", on = "Mon Dinner" }]\n')
        self.assertEqual(week["requests"], (("Stew", None), ("Curry", "Mon Dinner")))
        with self.assertRaises(tool.WeekError):
            read(WEEK + "cook = [3]\n")

    def test_the_problem_has_the_session(self):
        problem, ev = made_ahead()
        self.assertEqual(problem.preps, (SESSION,))
        self.assertTrue(ev.feasible)
        self.assertEqual(ev.slot_details[0]["prep"], "Mon 28 Sep Prep")
        self.assertIn("made at Mon 28 Sep Prep: omelette for 2 servings", describe_plan(problem, ev))

    def test_a_dish_already_committed_at_the_session_takes_its_place(self):
        g = kitchen()
        add_entry(g, "made", "omelette", at(28, 10), servings=2.0)
        g.add("QuantitySpecification", "nobody", value=0.0, unit="servings")
        g.nodes["made"]["hasPlannedConsumption"] = Ref("nobody")
        problem = build_problem(g, "week", DINNERS, NOW, leftover_days=3, preps=(SESSION,))
        self.assertEqual(problem.preps, ())                 # its one dish is made
        self.assertIn("Mon 28 Sep Prep already makes made", problem.notes)


class Written(unittest.TestCase):
    def test_the_session_cooks_everything_and_the_meals_eat_its_leftovers(self):
        problem, ev = made_ahead()
        writer = Recorder()
        commit_plan(writer, "week", problem, ev)
        entries = {w[1]: w[2] for w in writer.writes if w[0] == "MealPlanEntry"}
        prep = entries["Mon 28 Sep Prep -- omelette (Mon dinner)"]
        self.assertEqual((prep["references"], prep["hasPlannedServings"]), ("omelette", 2.0))
        nobody = next(w[2] for w in writer.writes if w[1] == "Mon 28 Sep Prep -- omelette (Mon dinner) servings eaten")
        self.assertEqual((nobody["value"], nobody["unit"]), (0.0, "servings"))
        region = next(w[2] for w in writer.writes if w[1] == "Mon 28 Sep Prep -- omelette (Mon dinner) region")
        self.assertEqual(region["hasBeginning"], "2026-09-28T10:00:00+0000")
        for meal in ("Mon dinner -- omelette", "Tue dinner -- omelette"):
            self.assertEqual(entries[meal]["consumesLeftoverFrom"], "MealPlanEntry:Mon 28 Sep Prep -- omelette (Mon dinner)")
            self.assertNotIn("references", entries[meal])

    def test_the_kept_proposal_says_where_a_dish_is_made(self):
        problem, ev = made_ahead()
        data = to_data(problem, ev, "2026-09-28")
        self.assertEqual(data["meals"][0]["made_at"], "Mon 28 Sep Prep")
        self.assertEqual(picks_from(problem, data), ev.picks)


class Reported(unittest.TestCase):
    def test_a_day_holding_only_a_dish_no_one_eats_is_not_judged(self):
        g = kitchen()
        add_target(g, "floor", 10, None)
        add_entry(g, "made", "omelette", at(27, 10), servings=2.0)
        g.add("QuantitySpecification", "nobody", value=0.0, unit="servings")
        g.nodes["made"]["hasPlannedConsumption"] = Ref("nobody")
        add_entry(g, "eaten", None, at(28, 18), leftover_of="made")
        days = [row["group"] for row in nutrition_report(g, "week")]
        self.assertEqual(days, ["2026-09-28"])


if __name__ == "__main__":
    unittest.main()
