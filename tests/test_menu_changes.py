"""Changing a committed week as it goes (mealplanner/menu_changes.py; data-model.md J34): a meal
skipped, what was eaten instead, the leftovers it takes with it, undoing it; what the nutrition
report, the week file's template and the planner then make of it.

The week: Monday's dinner cooks soup for Jamie and Alex, a serving each, and Tuesday's lunch is its
leftovers. The book also has tacos, in two versions.
"""

import unittest
from datetime import datetime, timezone

from mealplanner.menu_changes import MenuError, book_recipe, skip, unskip
from mealplanner.nutrition_scope import nutrition_report
from mealplanner.pantry import PantryError, cook
from mealplanner.planning.diagnose import settled
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.model import Fixed, Pick, Weights
from mealplanner.planning.search import exact
from tests.fakegraph import Ref, WritableGraph, at
from tests.planning_fixtures import MEALS, problem, protein_target, slot, when
from tests.test_household_graph import household, share
from tests.test_plan_week_tool import WEEK, read, tool
from tests.planning_graph import add_entry


def week():
    g = WritableGraph()
    g.add("Person", "p-jamie", "Jamie")
    g.add("Person", "p-alex", "Alex")
    for recipe, versions in (("Soup", (1,)), ("Tacos", (1, 2))):
        g.add("RecipeIdentity", f"r-{recipe}", recipe)
        for v in versions:
            g.add("Plan", f"{recipe} v{v}", f"{recipe} v{v}", specializationOf=Ref(f"r-{recipe}"))
    g.add("MealPlan", "wk", "Week of 2026-10-26", hasEntry=[])
    g.post("/structr/rest/TemporalRegion", {"name": "mon region", "hasBeginning": "2026-10-27T00:30:00+0000",
                                            "hasEnd": "2026-10-27T01:30:00+0000"})
    g.post("/structr/rest/TemporalRegion", {"name": "tue region", "hasBeginning": "2026-10-27T18:30:00+0000"})
    g.post("/structr/rest/MealPlanEntry", {"name": "Mon 26 Oct Dinner -- Soup v1", "memberOf": "wk", "isSkipped": False,
                                           "references": "Soup v1", "hasPlannedServings": 4.0,
                                           "isAbout": "TemporalRegion:mon region"})
    g.post("/structr/rest/MealPlanEntry", {"name": "Tue 27 Oct Lunch -- Soup v1", "memberOf": "wk", "isSkipped": False,
                                           "consumesLeftoverFrom": "MealPlanEntry:Mon 26 Oct Dinner -- Soup v1",
                                           "isAbout": "TemporalRegion:tue region"})
    for who, person in (("Jamie", "p-jamie"), ("Alex", "p-alex")):
        g.post("/structr/rest/QuantitySpecification", {"name": f"mon {who} q", "value": 1.0, "unit": "servings"})
        g.post("/structr/rest/MealShare", {"name": f"mon {who}", "shareOf": "MealPlanEntry:Mon 26 Oct Dinner -- Soup v1",
                                           "eatenBy": person, "hasPlannedConsumption": f"QuantitySpecification:mon {who} q"})
    return g


DINNER, LUNCH = "MealPlanEntry:Mon 26 Oct Dinner -- Soup v1", "MealPlanEntry:Tue 27 Oct Lunch -- Soup v1"


def ref_id(value):
    return getattr(value, "id", value)


class Skipped(unittest.TestCase):
    def test_nothing_instead_frees_the_meal_and_its_leftovers(self):
        g = week()
        change = skip(g, DINNER)
        self.assertEqual(change.skipped, ["Mon 26 Oct Dinner -- Soup v1", "Tue 27 Oct Lunch -- Soup v1"])
        self.assertTrue(g.nodes[DINNER]["isSkipped"] and g.nodes[LUNCH]["isSkipped"])
        self.assertIsNone(g.nodes[DINNER]["eatenInstead"])
        self.assertIn("Tue 27 Oct Lunch -- Soup v1: skipped too, as there are no leftovers to eat.", change.notes)

    def test_a_recipe_from_the_book_is_planned_in_its_place_for_the_same_people(self):
        g = week()
        change = skip(g, DINNER, "  tacos ")
        name = "Mon 26 Oct Dinner -- Tacos v2"                                  # the newest version
        made = g.nodes[f"MealPlanEntry:{name}"]
        self.assertEqual((ref_id(made["references"]), made["hasPlannedServings"], made["isSkipped"], ref_id(made["memberOf"])),
                         ("Tacos v2", 2.0, False, "wk"))
        region = g.nodes[ref_id(made["isAbout"])]
        self.assertEqual((region["hasBeginning"], region["hasEnd"]), ("2026-10-27T00:30:00+0000", "2026-10-27T01:30:00+0000"))
        self.assertEqual(g.nodes[ref_id(made["hasPlannedConsumption"])]["value"], 2.0)
        shares = sorted((ref_id(g.nodes[f"MealShare:{name} -- {who}"]["eatenBy"]), g.nodes[f"QuantitySpecification:{name} -- {who} servings"]["value"])
                        for who in ("Jamie", "Alex"))
        self.assertEqual(shares, [("p-alex", 1.0), ("p-jamie", 1.0)])
        for node_name in change.created:
            node = next(n for n in g.nodes.values() if n["name"] == node_name)
            self.assertEqual((node["visibleToAuthenticatedUsers"], node["visibleToPublicUsers"]), (True, False), node_name)
        self.assertIsNone(g.nodes[DINNER]["eatenInstead"])
        self.assertEqual(book_recipe(g, "TACOS V1")["id"], "Tacos v1")
        self.assertIsNone(book_recipe(g, "takeout"))

    def test_anything_else_is_kept_in_its_words(self):
        g = week()
        change = skip(g, DINNER, "takeout   pizza")
        self.assertEqual(g.nodes[DINNER]["eatenInstead"], "takeout pizza")
        self.assertIn("Mon 26 Oct Dinner -- Soup v1: skipped; takeout pizza eaten instead, which the book has no figures for.", change.notes)

    def test_what_cannot_be_skipped(self):
        g = week()
        g.nodes[DINNER]["fulfilledBy"] = Ref("Soup v1")                          # any cook will do
        with self.assertRaises(MenuError):
            skip(g, DINNER)
        g = week()
        skip(g, LUNCH)
        with self.assertRaises(MenuError):
            skip(g, LUNCH)
        with self.assertRaises(MenuError):
            skip(g, "no such entry")
        with self.assertRaises(MenuError):
            skip(g, DINNER, "soup v1")                                          # the meal skipped is no replacement
        with self.assertRaises(PantryError):
            cook(g, LUNCH, datetime(2026, 10, 27, tzinfo=timezone.utc), "t1")


class Undone(unittest.TestCase):
    def test_undoing_restores_the_leftovers_it_took(self):
        g = week()
        skip(g, DINNER, "takeout")
        change = unskip(g, DINNER)
        self.assertEqual(change.restored, ["Mon 26 Oct Dinner -- Soup v1", "Tue 27 Oct Lunch -- Soup v1"])
        self.assertFalse(g.nodes[DINNER]["isSkipped"] or g.nodes[LUNCH]["isSkipped"])
        self.assertIsNone(g.nodes[DINNER]["eatenInstead"])

    def test_a_leftover_skipped_for_itself_stays_skipped(self):
        g = week()
        skip(g, LUNCH, "a sandwich")
        skip(g, DINNER)
        self.assertEqual(unskip(g, DINNER).restored, ["Mon 26 Oct Dinner -- Soup v1"])
        self.assertTrue(g.nodes[LUNCH]["isSkipped"])

    def test_not_while_another_meal_holds_its_time_or_its_source_is_skipped(self):
        g = week()
        skip(g, DINNER, "tacos")
        with self.assertRaises(MenuError) as caught:
            unskip(g, DINNER)
        self.assertIn("Mon 26 Oct Dinner -- Tacos v2 is planned at this meal now; skip it first", str(caught.exception))
        with self.assertRaises(MenuError):
            unskip(g, LUNCH)                                                    # its soup was never made
        skip(g, "MealPlanEntry:Mon 26 Oct Dinner -- Tacos v2")
        unskip(g, DINNER)
        self.assertFalse(g.nodes[DINNER]["isSkipped"])


class Nutrition(unittest.TestCase):
    def test_a_meal_eaten_instead_leaves_its_peoples_day_unknown(self):
        g = household()
        add_entry(g, "e1", "omelette", at(28, 8), servings=1.0)
        add_entry(g, "e2", "omelette", at(28, 18), servings=1.0)
        share(g, "e1", "p-jamie", 1.0)
        share(g, "e2", "p-jamie", 1.0)
        g.nodes["e2"].update(isSkipped=True, eatenInstead="takeout")
        rows = {r["target"]: r for r in nutrition_report(g, "week")}
        self.assertEqual((rows["jamie floor"]["status"], rows["jamie floor"]["total"]), ("indeterminate", 29.0))
        self.assertIn("e2 (takeout instead)", rows["jamie floor"]["unknown"])
        self.assertEqual(rows["alex cap"]["status"], "ok")                          # Alex ate neither
        g.nodes["e2"]["eatenInstead"] = None                                        # skipped, nothing instead
        self.assertEqual(nutrition_report(g, "week")[0]["unknown"], [])


class TheWeekUnderWay(unittest.TestCase):
    def graph(self, *entries):
        from tests.fakegraph import FakeGraph
        g = FakeGraph()
        refs = []
        for i, (begins, skipped, instead) in enumerate(entries):
            g.add("TemporalRegion", f"r{i}", hasBeginning=begins)
            g.add("MealPlanEntry", f"e{i}", isAbout=Ref(f"r{i}"), isSkipped=skipped, eatenInstead=instead)
            refs.append(Ref(f"e{i}"))
        g.add("MealPlan", "week", hasEntry=refs)
        return g

    def test_only_the_free_meals_still_to_come_are_planned(self):
        week_file = read(WEEK)                                     # Mon 5 and Tue 6 Oct, breakfast 08:00 and dinner 18:30 Edmonton
        g = self.graph(("2026-10-05T14:00:00+0000", True, None),     # Mon breakfast, skipped, nothing instead: past
                       ("2026-10-06T00:30:00+0000", False, None),    # Mon dinner, eaten
                       ("2026-10-06T14:00:00+0000", True, "cereal"),  # Tue breakfast, something else instead
                       ("2026-10-07T00:30:00+0000", True, None))     # Tue dinner, skipped: free
        notes = []
        now = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
        self.assertEqual([s.key for s in tool.template(g, "week", week_file, now, notes)], ["Tue 06 Oct Dinner"])
        self.assertEqual(notes, ["the week is under way: 1 free meal already past is not planned again"])
        fresh = self.graph()
        self.assertEqual(len(tool.template(fresh, "week", week_file, now)), 4)     # not under way: as before

    def test_the_stock_and_waste_weights_are_the_week_files(self):
        self.assertEqual(read(WEEK + "[weights]\nstock = 0.5\nwaste = 1\n")["weights"], {"stock": 0.5, "waste": 1})
        for bad in ("-1", '"lots"'):
            with self.assertRaises(tool.WeekError):
                read(WEEK + f"[weights]\nstock = {bad}\n")


class Settled(unittest.TestCase):
    def test_a_day_already_eaten_that_missed_does_not_stop_the_rest_of_the_week(self):
        eaten = Fixed(eaten=1.0, candidate="buttered pasta")                          # 12 g of protein, against 30
        p = problem([slot("yesterday", when(27, 18), fixed=eaten), slot("dinner", when(28, 18))], MEALS,
                    [protein_target(30, None)], weights=Weights())
        best = exact(p).best
        self.assertTrue(best.feasible)
        self.assertEqual(settled(p), ["settled before this plan, so not judged: protein target on 2026-09-27: "
                                      "12 against a minimum of 30 (18 short)"])
        self.assertFalse(evaluate(p, (Pick(candidate="buttered pasta"), Pick(candidate="veggie stir-fry"))).feasible)  # today still counts


if __name__ == "__main__":
    unittest.main()
