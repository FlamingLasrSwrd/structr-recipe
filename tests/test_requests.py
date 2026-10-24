"""Recipes asked for a week from the recipe pages (mealplanner/requests.py; data-model.md J33): the
next week to plan, a request written on its MealPlan and taken back, and the planner reading it
beside the week file's (planning/extract.build_problem).
"""

import unittest
from datetime import date

from mealplanner.planning.extract import RequestError, build_problem
from mealplanner.requests import ask, next_week_start, requested, week_start, withdraw
from tests.fakegraph import Ref, WritableGraph
from tests.test_plan_week_tool import tool
from tests.test_planning_extract import DINNERS, NOW, kitchen

SATURDAY, MONDAY = date(2026, 10, 24), date(2026, 10, 26)


def weeks(*committed, empty=()):
    g = WritableGraph()
    g.add("RecipeIdentity", "r-soup", "Black bean soup")
    g.add("RecipeIdentity", "r-oats", "Overnight oats")
    for start in committed:
        g.add("MealPlan", f"mp-{start}", f"Week of {start}", hasEntry=[Ref("r-soup")])     # any entry will do
    for start in empty:
        g.add("MealPlan", f"mp-{start}", f"Week of {start}", hasEntry=[])
    g.add("MealPlan", "mp-other", "A week of my own", hasEntry=[Ref("r-soup")])
    return g


class TheNextWeek(unittest.TestCase):
    def test_the_week_after_the_latest_planned(self):
        self.assertEqual(next_week_start(weeks("2026-10-19", "2026-10-26"), SATURDAY), date(2026, 11, 2))
        self.assertEqual(next_week_start(weeks("2026-10-19"), SATURDAY), MONDAY)

    def test_once_that_week_has_begun_the_first_from_today(self):
        self.assertEqual(next_week_start(weeks("2026-10-05"), SATURDAY), MONDAY)
        self.assertEqual(next_week_start(weeks("2026-10-12"), MONDAY), MONDAY)       # begins today, unplanned

    def test_with_none_planned_the_coming_monday(self):
        self.assertEqual(next_week_start(weeks(empty=("2026-11-09",)), SATURDAY), MONDAY)
        self.assertEqual(next_week_start(weeks(), MONDAY), date(2026, 11, 2))

    def test_the_name_says_the_week(self):
        self.assertEqual(week_start({"name": "Week of 2026-10-26"}), MONDAY)
        self.assertIsNone(week_start({"name": "Week of 26 Oct"}))


class Asked(unittest.TestCase):
    def test_asked_for_once_makes_the_week_and_twice_writes_nothing(self):
        g = weeks("2026-10-26")
        self.assertTrue(ask(g, "r-soup", date(2026, 11, 2)))
        week = g.nodes["MealPlan:Week of 2026-11-02"]
        self.assertEqual((week["visibleToAuthenticatedUsers"], week["visibleToPublicUsers"]), (True, False))
        posts, patches = g.posts, g.patches
        self.assertFalse(ask(g, "r-soup", date(2026, 11, 2)))
        self.assertEqual((g.posts, g.patches), (posts, patches))
        self.assertTrue(ask(g, "r-oats", date(2026, 11, 2)))
        self.assertEqual([r["name"] for r in requested(g, date(2026, 11, 2))], ["Black bean soup", "Overnight oats"])
        self.assertEqual(next_week_start(g, SATURDAY), date(2026, 11, 2))         # a week only asked for is not planned

    def test_an_existing_week_is_used_and_taken_back(self):
        g = weeks(empty=("2026-11-02",))
        ask(g, "r-soup", date(2026, 11, 2))
        self.assertEqual(len([n for n in g.nodes.values() if n["type"] == "MealPlan" and n["name"] == "Week of 2026-11-02"]), 1)
        self.assertTrue(withdraw(g, "r-soup", date(2026, 11, 2)))
        self.assertEqual(requested(g, date(2026, 11, 2)), [])
        self.assertFalse(withdraw(g, "r-soup", date(2026, 11, 2)))
        self.assertFalse(withdraw(g, "r-soup", date(2026, 11, 9)))                # no such week


class Planned(unittest.TestCase):
    def test_the_planner_cooks_what_the_pages_asked_for(self):
        g = kitchen()
        g.nodes["week"]["requestsRecipe"] = [Ref("recipe omelette")]
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual([(r.name, r.slot) for r in p.requests], [("recipe omelette", None)])
        self.assertIn("asked for from the recipe pages: recipe omelette", p.notes)

    def test_named_in_the_week_file_too_it_is_asked_for_once(self):
        g = kitchen()
        g.nodes["week"]["requestsRecipe"] = [Ref("recipe omelette")]
        p = build_problem(g, "week", DINNERS, NOW, requests=(("recipe omelette", "Tue Dinner"),))
        self.assertEqual([(r.name, r.slot) for r in p.requests], [("recipe omelette", 1)])

    def test_the_tool_names_another_weeks_requests_until_that_week_is_over(self):
        g = weeks("2026-10-26")
        ask(g, "r-soup", date(2026, 11, 2))
        ask(g, "r-oats", date(2026, 10, 12))                                        # a week that went unplanned
        self.assertEqual(tool.requests_elsewhere(g, "mp-2026-11-09", SATURDAY),
                         ["note: Week of 2026-11-02, not this week, has recipes asked for from the recipe pages: Black bean soup"])
        self.assertEqual(tool.requests_elsewhere(g, "MealPlan:Week of 2026-11-02", SATURDAY), [])

    def test_a_recipe_with_no_version_left_is_named(self):
        g = kitchen()
        g.add("RecipeIdentity", "r-gone", "Gone soup")
        g.nodes["week"]["requestsRecipe"] = [Ref("r-gone")]
        with self.assertRaises(RequestError):
            build_problem(g, "week", DINNERS, NOW)


if __name__ == "__main__":
    unittest.main()
