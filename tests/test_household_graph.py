"""A household's week read from and written to the graph (data-model.md Sec 19; planning/extract.py,
planning/commit.py, nutrition_scope.nutrition_report).

Worked out by hand from tests/test_planning_extract.py's kitchen: an omelette has 24 g protein a
serving. Elijah's baseline is a shake with 5 g of protein a day; Cass has none.
  A committed omelette, 1.5 servings Elijah's and 0.5 Cass's: Elijah 36 + 5 = 41 g that day, Cass 12 g.
"""

import unittest

from mealplanner.nutrition_scope import nutrition_report, week_totals
from mealplanner.planning.commit import commit_plan
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick
from tests.fakegraph import Ref, at, when
from tests.planning_graph import Recorder, add_entry, add_recipe, add_target
from tests.test_planning_extract import NOW, kitchen


def household(week="week"):
    g = kitchen()
    add_recipe(g, "shake", output_grams=50, protein_per_100g=10, provenance="sourced", yield_servings=1, minutes=1)
    g.add("Person", "p-eli", "Elijah", hasBaseline=[Ref("shake")])
    g.add("Person", "p-cass", "Cass", hasBaseline=[])
    g.add("Household", "home", "Home", members=[Ref("p-eli"), Ref("p-cass")])
    g.nodes[week]["forHousehold"] = Ref("home")
    for name, lo, hi, person in (("eli floor", 20, None, "p-eli"), ("cass cap", None, 30, "p-cass"), ("nobody's", 1, None, None)):
        add_target(g, name, lo, hi, strictness="soft", weight=0.3)
        if person:
            g.nodes[name]["forPerson"] = Ref(person)
    return g


def share(g, entry, person, servings):
    g.add("QuantitySpecification", f"{entry} {person} q", value=servings, unit="servings")
    g.add("MealShare", f"{entry} {person}", f"{entry} {person}", eatenBy=Ref(person), hasPlannedConsumption=Ref(f"{entry} {person} q"))
    g.nodes[entry].setdefault("hasShare", []).append(Ref(f"{entry} {person}"))


class Extract(unittest.TestCase):
    def test_the_household_is_the_eaters_with_their_targets_and_baselines(self):
        p = build_problem(household(), "week", [SlotSpec(when(28, 18), "Dinner", "dinner")], NOW)
        self.assertEqual((p.eaters, p.eater_names), (("p-cass", "p-eli"), {"p-cass": "Cass", "p-eli": "Elijah"}))
        self.assertEqual({t.name: t.eater for t in p.targets}, {"eli floor": "p-eli", "cass cap": "p-cass"})
        self.assertTrue(any("nobody's" in n and "for no one in the household" in n for n in p.notes))
        self.assertEqual(p.baselines, {"p-eli": {"Protein": 5.0}})
        self.assertEqual(p.baseline, {})                             # the week itself has none
        self.assertFalse(any(n.startswith("baseline counted") for n in p.notes))
        self.assertNotIn("shake", p.candidates)                      # a baseline is not a meal

    def test_meal_eaters_and_portions_are_named_by_person(self):
        slots = [SlotSpec(when(28, 8), "Dinner", "breakfast", ("Elijah",)), SlotSpec(when(28, 18), "Dinner", "dinner")]
        p = build_problem(household(), "week", slots, NOW, eater_portions={"Cass": (0.5, 1.0)})
        self.assertEqual([s.eaters for s in p.slots], [("p-eli",), None])
        self.assertEqual(p.eater_portions, {"p-cass": (0.5, 1.0)})
        with self.assertRaises(ValueError):
            build_problem(household(), "week", [SlotSpec(when(28, 8), "Dinner", "b", ("Robin",))], NOW)
        with self.assertRaises(ValueError):
            build_problem(household(), "week", slots, NOW, eater_portions={"Robin": (1.0,)})

    def test_a_committed_meal_keeps_who_ate_what(self):
        g = household()
        add_entry(g, "e1", "omelette", at(28, 18), servings=2.0)
        share(g, "e1", "p-eli", 1.5)
        share(g, "e1", "p-cass", 0.5)
        add_entry(g, "e2", "omelette", at(29, 18), servings=1.0)          # from before households: no shares
        p = build_problem(g, "week", [], NOW)
        by_name = {s.key: s for s in p.slots}
        self.assertEqual(by_name["e1"].fixed.shares, (("p-cass", 0.5), ("p-eli", 1.5)))
        self.assertEqual(by_name["e1"].eaters, ("p-cass", "p-eli"))
        self.assertTrue(any("'e2' says nothing of who ate it: counted as Cass's" in n for n in p.notes))


class Commit(unittest.TestCase):
    def test_each_eater_gets_a_meal_share(self):
        p = build_problem(household(), "week", [SlotSpec(when(28, 18), "Dinner", "dinner")], NOW,
                          eater_portions={"Cass": (0.5, 1.0), "Elijah": (1.0, 1.5)})
        ev = evaluate(p, [Pick(candidate="omelette", shares=(0.5, 1.5))])
        writer = Recorder()
        commit_plan(writer, "week", p, ev)
        entry = next(w for w in writer.writes if w[0] == "MealPlanEntry")
        self.assertEqual(entry[2]["hasPlannedServings"], 2.0)
        shares = {w[1]: w[2] for w in writer.writes if w[0] == "MealShare"}
        self.assertEqual(sorted(shares), ["dinner -- omelette -- Cass", "dinner -- omelette -- Elijah"])
        self.assertEqual(shares["dinner -- omelette -- Elijah"]["eatenBy"], "p-eli")
        servings = {w[1]: w[2]["value"] for w in writer.writes if w[0] == "QuantitySpecification" and w[1].endswith("servings")}
        self.assertEqual(servings["dinner -- omelette -- Cass servings"], 0.5)
        self.assertEqual(shares["dinner -- omelette -- Cass"]["hasPlannedConsumption"],
                         "QuantitySpecification:dinner -- omelette -- Cass servings")


class Report(unittest.TestCase):
    def test_each_persons_target_counts_their_share_and_their_baseline(self):
        g = household()
        add_entry(g, "e1", "omelette", at(28, 18), servings=2.0)
        share(g, "e1", "p-eli", 1.5)
        share(g, "e1", "p-cass", 0.5)
        rows = {r["target"]: r for r in nutrition_report(g, "week")}
        self.assertEqual((rows["eli floor"]["total"], rows["cass cap"]["total"]), (41.0, 12.0))

    def test_a_meal_someone_does_not_eat_adds_nothing_to_their_day(self):
        g = household()
        add_entry(g, "e1", "omelette", at(28, 18), servings=2.0)
        share(g, "e1", "p-eli", 1.5)                                   # Cass is out that evening
        rows = {r["target"]: r for r in nutrition_report(g, "week")}
        self.assertEqual((rows["eli floor"]["total"], rows["cass cap"]["total"]), (41.0, 0.0))

    def test_a_weekly_target_counts_the_baseline_once_for_each_day_with_meals(self):
        g = household()
        add_target(g, "eli week", 50, None, scope="weekly", strictness="soft", weight=0.3)
        g.nodes["eli week"]["forPerson"] = Ref("p-eli")
        for name, day, servings in (("e1", 28, 1.5), ("e2", 29, 1.0)):
            add_entry(g, name, "omelette", at(day, 18), servings=2.0)
            share(g, name, "p-eli", servings)
        (row,) = [r for r in nutrition_report(g, "week") if r["target"] == "eli week"]
        self.assertEqual((row["group"], row["total"], row["status"]), ("week", 36.0 + 24.0 + 2 * 5.0, "ok"))

    def test_a_per_meal_target_counts_each_meal_alone_without_the_baseline(self):
        g = household()
        add_target(g, "eli meal", 30, None, scope="per_meal", strictness="soft", weight=0.3)
        g.nodes["eli meal"]["forPerson"] = Ref("p-eli")
        for name, day, servings in (("e1", 28, 1.5), ("e2", 29, 1.0)):
            add_entry(g, name, "omelette", at(day, 18), servings=2.0)
            share(g, name, "p-eli", servings)
        rows = {r["group"]: r for r in nutrition_report(g, "week") if r["target"] == "eli meal"}
        self.assertEqual({k: (r["total"], r["status"]) for k, r in rows.items()}, {"e1": (36.0, "ok"), "e2": (24.0, "below_min")})

    def test_servings_not_stated_in_servings_are_taken_as_one_and_said_so(self):
        g = household()
        add_entry(g, "e1", "omelette", at(28, 18), servings=2.0)
        g.add("QuantitySpecification", "e1 eaten", value=2.0, unit="g")
        g.nodes["e1"]["hasPlannedConsumption"] = Ref("e1 eaten")
        (row,) = [r for r in nutrition_report(g, "week") if r["target"] == "nobody's"]
        self.assertEqual((row["total"], row["assumed_default_servings"]), (24.0, ["e1"]))


class WeekTotals(unittest.TestCase):
    """nutrition_scope.week_totals: a daily target's days added up and judged against its range times
    the days judged (the owner's request, 2026-10-24)."""

    def week(self, eli, cass):
        g = household()
        for name, day, e, c in zip(("e1", "e2"), (28, 29), eli, cass):
            add_entry(g, name, "omelette", at(day, 18), servings=e + c)
            share(g, name, "p-eli", e)
            share(g, name, "p-cass", c)
        return {r["target"]: r for r in week_totals(nutrition_report(g, "week"))}

    def test_a_short_day_made_up_on_another_meets_the_week(self):
        rows = self.week(eli=(1.5, 0.5), cass=(0.5, 0.5))          # Elijah 41 g, then 17 g: under 20 that day
        eli = rows["eli floor"]
        self.assertEqual((eli["group"], eli["days"], eli["total"], eli["week_min"], eli["week_max"]), ("week", 2, 58.0, 40.0, None))
        self.assertEqual((eli["status"], eli["day_statuses"]), ("ok", {"ok": 1, "below_min": 1}))

    def test_under_and_over_for_the_week(self):
        rows = self.week(eli=(0.5, 0.5), cass=(1.5, 1.5))          # Elijah 17 g a day; Cass 36 g a day, capped at 30
        self.assertEqual((rows["eli floor"]["total"], rows["eli floor"]["status"]), (34.0, "below_min"))
        self.assertEqual((rows["cass cap"]["total"], rows["cass cap"]["week_max"], rows["cass cap"]["status"]), (72.0, 60.0, "above_max"))

    def test_only_daily_targets_and_an_unknown_day_leaves_it_open(self):
        g = household()
        add_target(g, "eli week", 50, None, scope="weekly", strictness="soft", weight=0.3)
        add_recipe(g, "mystery", output_grams=100, protein_per_100g=None, provenance="sourced", yield_servings=1, minutes=5)
        add_entry(g, "e1", "omelette", at(28, 18), servings=1.0)
        add_entry(g, "e2", "mystery", at(29, 18), servings=1.0)
        rows = {r["target"]: r for r in week_totals(nutrition_report(g, "week"))}
        self.assertNotIn("eli week", rows)
        self.assertEqual((rows["nobody's"]["total"], rows["nobody's"]["status"], rows["nobody's"]["unknown"]), (24.0, "indeterminate", ["e2"]))


if __name__ == "__main__":
    unittest.main()
