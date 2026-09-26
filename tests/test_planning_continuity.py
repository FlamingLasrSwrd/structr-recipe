"""A one-slot problem must score every recipe exactly as the selector does.

The planner is the selector generalised to a whole week; it earns the right to
replace it only if the two agree where they overlap (docs/optimizer-design.md
Sec 4.5, "continuity"). Both run here on the SAME graph, with variety, a soft and
a hard-maximum nutrition target, a soft exclusion, stock coverage and expiry
urgency all active. The planner eats a recipe's whole yield in the one slot, since
the selector prices a recipe's stock demand as the whole batch.

What does NOT carry over, by design: a hard MINIMUM is a constraint for the planner
but only a score for the selector, and a recipe whose nutrition is placeholder is
ineligible under a hard target. The recipes here avoid both.
"""

import importlib.util
import os
import unittest

os.environ.setdefault("STRUCTR_SUPERUSER_PASSWORD", "unused-in-tests")
_spec = importlib.util.spec_from_file_location(
    "selector_11c", os.path.join(os.path.dirname(__file__), "..", "scripts", "11c_simple_selector.py"))
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)

from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick
from mealplanner.planning.search import exact
from tests.fakegraph import Ref, at, when
from tests.planning_graph import add_entry, add_portion, add_recipe, add_target, add_type, new_kitchen

NOW = when(28, 18)


def shared_kitchen():
    g = new_kitchen()
    g.nodes["week"].update(varietyWeight=0.3, stockWeight=0.4, wasteWeight=0.5, timeBudgetWeight=0.6, timeBudgetMinutes=30.0)
    add_recipe(g, "omelette", output_grams=400, protein_per_100g=12, provenance="sourced", yield_servings=2, minutes=35,
               inputs=[("Eggs", 300.0)])
    add_recipe(g, "pasta", output_grams=300, protein_per_100g=8, provenance="sourced", yield_servings=2, minutes=20,
               inputs=[("Noodles", 200.0), ("Eggs", 100.0)])
    add_recipe(g, "curry", output_grams=500, protein_per_100g=6, provenance="sourced", yield_servings=2, minutes=None,
               inputs=[("Chili", 50.0)])
    add_target(g, "protein range", 40, 100, strictness="soft", weight=0.3)
    add_target(g, "protein ceiling", None, 200, strictness="hard", weight=0.1)
    g.add("ExclusionConstraint", "mild please", "mild please", appliesTo=Ref("Chili"), strictness="soft", weight=0.15)
    # variety: the omelette was eaten five days ago, in another plan
    g.add("MealPlan", "last week", "last week", hasEntry=[], hasConstraint=[])
    add_entry(g, "old omelette", "omelette", at(23, 18), servings=2, week="last week")
    # stock: 250 g of eggs, weighed on the 25th, keeping 5 days (Fresh Meat, fridge, sealed)
    for name in ("Fresh Meat", "ShelfLife", "Fridge", "Sealed"):
        add_type(g, name)
    g.add("QuantitySpecification", "five days", value=5.0, unit="days")
    g.add("DefaultSpecification", "meat default", hasKind=Ref("ShelfLife"), keyedBy=[Ref("Fridge"), Ref("Sealed")], hasValue=Ref("five days"))
    g.nodes["Fresh Meat"]["defaultSpecifications"].append(Ref("meat default"))
    add_portion(g, "eggs a", "Eggs", 250.0, hour_iso=at(25, 0))
    g.nodes["eggs a"]["hasPerishabilityType"] = Ref("Fresh Meat")
    return g


class OneSlotAgreesWithTheSelector(unittest.TestCase):
    def setUp(self):
        self.g = shared_kitchen()
        self.problem = build_problem(self.g, "week", [SlotSpec(NOW, "Dinner")], NOW, servings_eaten=2.0)
        ranked = sel.select(self.g, "week", NOW, meal_type="Dinner", slot_start=NOW, servings_eaten=2.0)
        self.selector = {r["plan"]["name"]: r for r in ranked}

    def test_every_recipes_score_matches(self):
        self.assertEqual(set(self.selector), {"omelette", "pasta", "curry"})
        for name, row in self.selector.items():
            ev = evaluate(self.problem, (Pick(candidate=name),))
            self.assertFalse(row["disqualified"], name)
            self.assertTrue(ev.feasible, name)
            self.assertAlmostEqual(ev.objective, row["score"], places=9, msg=f"{name}: planner {ev.terms} vs selector {row['score']} ({row['reason']})")

    def test_the_winner_is_the_same(self):
        winner = max((r for r in self.selector.values() if not r["disqualified"]), key=lambda r: r["score"])["plan"]["name"]
        best = exact(self.problem).best
        self.assertEqual(self.problem.candidates[best.picks[0].candidate].name, winner)

    def test_the_terms_that_differ_between_recipes_are_actually_exercised(self):
        # guard against a vacuous agreement: variety, stock, waste, soft exclusion and time all vary across these three
        terms = {n: evaluate(self.problem, (Pick(candidate=n),)).terms for n in self.selector}
        for term in ("time", "variety", "stock", "waste", "soft_exclusion", "nutrition"):
            self.assertGreater(len({round(t[term], 9) for t in terms.values()}), 1, term)


if __name__ == "__main__":
    unittest.main()
