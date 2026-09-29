"""A household's week read from and written to the graph (data-model.md Sec 19; planning/extract.py,
planning/commit.py, nutrition_scope.nutrition_report).

Worked out by hand from tests/test_planning_extract.py's kitchen: an omelette has 24 g protein a
serving. Elijah's baseline is a shake with 5 g of protein a day; Cass has none.
  A committed omelette, 1.5 servings Elijah's and 0.5 Cass's: Elijah 36 + 5 = 41 g that day, Cass 12 g.
"""

import unittest

from mealplanner.nutrition_scope import nutrition_report
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


if __name__ == "__main__":
    unittest.main()
