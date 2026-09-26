"""build_problem(): the graph read into plain data, and commit_plan(): plain data written back.

Expected numbers come from the fixture's own quantities, worked out here:
  omelette  makes 400 g at 12 g protein/100 g = 48 g, for 2 servings  -> 24 g per serving
  pasta     makes 300 g at  8 g protein/100 g = 24 g, for 2 servings  -> 12 g per serving
"""

import unittest

from mealplanner.planning.commit import commit_plan
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick
from mealplanner.planning.plan import plan_week
from tests.fakegraph import Ref, at, when
from tests.planning_graph import Recorder, add_entry, add_portion, add_recipe, add_target, add_type, new_kitchen

NOW = when(28, 0)


def kitchen():
    g = new_kitchen()
    add_recipe(g, "omelette", output_grams=400, protein_per_100g=12, provenance="sourced", yield_servings=2, minutes=35,
               inputs=[("Eggs", 300.0)], difficulty="easy")
    add_recipe(g, "pasta", output_grams=300, protein_per_100g=8, provenance="placeholder", yield_servings=2, minutes=20,
               inputs=[("Noodles", 200.0), ("Eggs", 100.0)])
    return g


DINNERS = [SlotSpec(when(28, 18), "Dinner"), SlotSpec(when(29, 18), "Dinner")]


class Weights(unittest.TestCase):
    def test_the_meal_plans_weights_and_budget(self):
        p = build_problem(kitchen(), "week", DINNERS, NOW)
        w = p.weights
        self.assertEqual((w.time, w.variety, w.stock, w.waste, w.time_budget_minutes), (0.6, 0.0, 0.0, 0.0, 30.0))

    def test_a_zero_weight_is_kept_and_a_missing_one_takes_the_selectors_default(self):
        g = kitchen()
        del g.nodes["week"]["varietyWeight"]
        g.nodes["week"]["timeBudgetWeight"] = 0.0
        w = build_problem(g, "week", DINNERS, NOW).weights
        self.assertEqual((w.time, w.variety), (0.0, 0.5))


class Targets(unittest.TestCase):
    def test_a_hard_daily_target(self):
        g = kitchen()
        add_target(g, "protein floor", 70, 140, weight=0.3)
        (t,) = build_problem(g, "week", DINNERS, NOW).targets
        self.assertEqual((t.name, t.scope, t.minimum, t.maximum, t.hard, t.weight, t.nutrient_name),
                         ("protein floor", "daily", 70, 140, True, 0.3, "Protein"))

    def test_a_target_not_stated_in_grams_is_noted_and_left_out(self):
        g = kitchen()
        add_target(g, "odd", 1, 2, unit="mg")
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(p.targets, ())
        self.assertTrue(any("odd" in n and "isn't grams" in n for n in p.notes))


class Candidates(unittest.TestCase):
    def setUp(self):
        g = kitchen()
        add_target(g, "protein floor", 40, None)
        self.p = build_problem(g, "week", DINNERS, NOW)
        self.omelette, self.pasta = self.p.candidates["omelette"], self.p.candidates["pasta"]

    def test_grams_of_protein_per_serving(self):
        self.assertAlmostEqual(self.omelette.nutrients["Protein"], 24.0)
        self.assertAlmostEqual(self.pasta.nutrients["Protein"], 12.0)

    def test_only_sourced_figures_are_trusted(self):
        self.assertEqual(self.omelette.untrusted, frozenset())
        self.assertEqual(self.pasta.untrusted, frozenset({"Protein"}))

    def test_the_recipes_own_facts(self):
        self.assertEqual((self.omelette.minutes, self.omelette.difficulty, self.omelette.yield_servings, self.omelette.meal_types),
                         (35, "easy", 2.0, frozenset({"Dinner"})))

    def test_demand_is_per_batch_in_grams_by_pool(self):
        self.assertEqual(dict(self.omelette.demand), {"Eggs": 300.0})
        self.assertEqual(dict(self.pasta.demand), {"Noodles": 200.0, "Eggs": 100.0})

    def test_a_retired_recipe_is_left_out(self):
        g = kitchen()
        add_recipe(g, "old", output_grams=100, protein_per_100g=1, provenance="sourced", yield_servings=1, minutes=5, retired=True)
        self.assertNotIn("old", build_problem(g, "week", DINNERS, NOW).candidates)

    def test_a_recipe_with_no_yield_in_servings_is_left_out_and_noted(self):
        g = kitchen()
        add_recipe(g, "vague", output_grams=100, protein_per_100g=1, provenance="sourced", yield_servings=1, minutes=5, with_yield=False)
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertNotIn("vague", p.candidates)
        self.assertTrue(any("vague" in n and "no yield" in n for n in p.notes))

    def test_a_hard_exclusion_marks_the_recipe(self):
        g = kitchen()
        g.add("ExclusionConstraint", "no eggs", "no eggs", appliesTo=Ref("Eggs"), strictness="hard", weight=None)
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertTrue(p.candidates["omelette"].hard_excluded and p.candidates["pasta"].hard_excluded)

    def test_a_soft_exclusion_costs_its_weight(self):
        g = kitchen()
        g.add("ExclusionConstraint", "dislike noodles", "dislike noodles", appliesTo=Ref("Noodles"), strictness="soft", weight=0.25)
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual((p.candidates["pasta"].soft_penalty, p.candidates["omelette"].soft_penalty), (0.25, 0.0))
        self.assertFalse(p.candidates["pasta"].hard_excluded)

    def test_leftover_days_come_from_the_override_or_are_unplanned(self):
        self.assertIsNone(self.omelette.leftover_days)                 # no "Cooked Leftover" class in this kitchen
        p = build_problem(kitchen(), "week", DINNERS, NOW, leftover_days=3.0)
        self.assertEqual(p.candidates["omelette"].leftover_days, 3.0)

    def test_leftover_days_resolve_from_the_cooked_leftover_shelf_life(self):
        g = kitchen()
        for name in ("Cooked Leftover", "ShelfLife", "Fridge", "Sealed"):
            add_type(g, name)
        g.add("QuantitySpecification", "three days", value=3.0, unit="days")
        g.add("DefaultSpecification", "leftover default", hasKind=Ref("ShelfLife"), keyedBy=[Ref("Fridge"), Ref("Sealed")],
              hasValue=Ref("three days"))
        g.nodes["Cooked Leftover"]["defaultSpecifications"].append(Ref("leftover default"))
        self.assertEqual(build_problem(g, "week", DINNERS, NOW).candidates["omelette"].leftover_days, 3.0)


class UsesOutsideThePlan(unittest.TestCase):
    def test_other_plans_and_history_count_this_plans_own_and_skipped_entries_do_not(self):
        g = kitchen()
        g.add("MealPlan", "last week", "last week", hasEntry=[], hasConstraint=[])
        add_entry(g, "last tue", "omelette", at(22, 18), servings=2, week="last week")
        add_entry(g, "skipped", "omelette", at(23, 18), servings=2, skipped=True, week="last week")
        add_entry(g, "this thu", "omelette", at(30, 18), servings=2)          # in THIS plan: a fixed slot, not an outside use
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(p.candidates["omelette"].uses, (when(22, 18),))


class FixedEntries(unittest.TestCase):
    def test_an_existing_entry_becomes_a_fixed_slot_in_time_order(self):
        g = kitchen()
        add_entry(g, "fri dinner", "omelette", at(29, 12), servings=2)         # between the two open dinners
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual([s.key for s in p.slots], ["Mon 28 Sep 18:00 Dinner", "fri dinner", "Tue 29 Sep 18:00 Dinner"])
        self.assertIsNone(p.slots[0].fixed)
        fixed = p.slots[1].fixed
        self.assertEqual((fixed.candidate, fixed.eaten, fixed.cooked, fixed.entry_id), ("omelette", 1.0, 2, "fri dinner"))

    def test_a_leftover_entry_points_at_its_source_slot(self):
        g = kitchen()
        add_entry(g, "cook", "omelette", at(28, 12), servings=2)
        add_entry(g, "reheat", None, at(29, 12), leftover_of="cook")
        p = build_problem(g, "week", [SlotSpec(when(30, 18), "Dinner")], NOW)
        self.assertEqual([s.key for s in p.slots], ["cook", "reheat", "Wed 30 Sep 18:00 Dinner"])
        self.assertEqual(p.slots[1].fixed.source, 0)

    def test_a_leftover_entry_whose_source_is_elsewhere_is_ignored_with_a_note(self):
        g = kitchen()
        g.add("MealPlan", "other", "other", hasEntry=[], hasConstraint=[])
        add_entry(g, "away", "omelette", at(20, 12), servings=2, week="other")
        add_entry(g, "reheat", None, at(29, 12), leftover_of="away")
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(len(p.slots), 2)
        self.assertTrue(any("reheat" in n and "ignored" in n for n in p.notes))

    def test_a_skipped_entry_is_not_a_slot(self):
        g = kitchen()
        add_entry(g, "skipped", "omelette", at(28, 12), servings=2, skipped=True)
        self.assertEqual(len(build_problem(g, "week", DINNERS, NOW).slots), 2)


class Stock(unittest.TestCase):
    def test_lots_and_pools(self):
        g = kitchen()
        add_portion(g, "eggs a", "Eggs", 250.0)
        add_portion(g, "eggs b", "Eggs", 100.0)
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(sorted((lot.pool, lot.grams) for lot in p.lots), [("Eggs", 100.0), ("Eggs", 250.0)])


class EndToEnd(unittest.TestCase):
    def build(self, *targets):
        g = kitchen()
        for t in targets:
            add_target(g, *t[:3], **t[3])
        return g

    def test_a_hard_minimum_the_trusted_recipe_can_meet(self):
        g = self.build(("floor", 40, None, {}))
        # both slots are on the 28th, so the day's 40 g minimum needs two 24 g omelettes (48 g); pasta is placeholder data
        result = plan_week(g, "week", [SlotSpec(when(28, 12), "Dinner"), SlotSpec(when(28, 18), "Dinner")], NOW)
        self.assertTrue(result.feasible)
        self.assertEqual([d["recipe"] for d in result.evaluation.slot_details], ["omelette", "omelette"])

    def test_the_placeholder_recipe_is_never_used_to_meet_a_hard_target(self):
        g = self.build(("floor", 20, None, {}))
        result = plan_week(g, "week", DINNERS, NOW)
        self.assertNotIn("pasta", [d["recipe"] for d in result.evaluation.slot_details])

    def test_an_unreachable_hard_minimum_gives_a_diagnosis_not_a_plan(self):
        g = self.build(("floor", 100, None, {}))
        result = plan_week(g, "week", [SlotSpec(when(28, 12), "Dinner"), SlotSpec(when(28, 18), "Dinner")], NOW)
        self.assertFalse(result.feasible)
        self.assertIn("No plan meets every hard constraint.", result.text())
        self.assertIn("pasta: its Protein figure is placeholder", result.text())      # 100 g is out of reach: 2 x 24 g


class Commit(unittest.TestCase):
    def problem_and_plan(self, picks, leftover_days=3.0):
        g = kitchen()
        problem = build_problem(g, "week", [SlotSpec(when(28, 18), "Dinner", "Mon dinner"), SlotSpec(when(29, 18), "Dinner", "Tue dinner")],
                                NOW, leftover_days=leftover_days)
        return problem, evaluate(problem, picks)

    def test_a_fresh_cook_and_its_leftover_are_written_as_the_model_wants_them(self):
        problem, ev = self.problem_and_plan((Pick(candidate="omelette"), Pick(source=0)))
        writer = Recorder()
        ids = commit_plan(writer, "week", problem, ev, name_prefix="TEST -- ")
        cook = next(w for w in writer.writes if w[0] == "MealPlanEntry" and w[1] == "TEST -- Mon dinner -- omelette")
        reheat = next(w for w in writer.writes if w[0] == "MealPlanEntry" and w[1] == "TEST -- Tue dinner -- omelette")
        self.assertEqual((cook[2]["references"], cook[2]["hasPlannedServings"], cook[2]["memberOf"]), ("omelette", 2.0, "week"))
        self.assertNotIn("consumesLeftoverFrom", cook[2])
        self.assertEqual(reheat[2]["consumesLeftoverFrom"], "MealPlanEntry:TEST -- Mon dinner -- omelette")
        self.assertNotIn("references", reheat[2])                    # invariant 7: a leftover entry names no Plan
        self.assertNotIn("hasPlannedServings", reheat[2])
        self.assertEqual(len(ids), 2)

    def test_the_cook_lasts_as_long_as_the_recipe_takes(self):
        problem, ev = self.problem_and_plan((Pick(candidate="omelette"), Pick(candidate="omelette")))
        writer = Recorder()
        commit_plan(writer, "week", problem, ev)
        region = next(w for w in writer.writes if w[0] == "TemporalRegion")
        self.assertEqual((region[2]["hasBeginning"], region[2]["hasEnd"]), ("2026-09-28T18:00:00+0000", "2026-09-28T18:35:00+0000"))

    def test_an_infeasible_plan_is_never_written(self):
        g = kitchen()
        add_target(g, "floor", 100, None)
        problem = build_problem(g, "week", [SlotSpec(when(28, 18), "Dinner")], NOW)
        ev = evaluate(problem, (Pick(candidate="omelette"),))
        with self.assertRaises(ValueError):
            commit_plan(Recorder(), "week", problem, ev)

    def test_servings_eaten_other_than_one_are_recorded(self):
        g = kitchen()
        problem = build_problem(g, "week", [SlotSpec(when(28, 18), "Dinner", "Mon dinner")], NOW, servings_eaten=2.0)
        writer = Recorder()
        commit_plan(writer, "week", problem, evaluate(problem, (Pick(candidate="omelette"),)))
        entry = next(w for w in writer.writes if w[0] == "MealPlanEntry")
        self.assertEqual(entry[2]["hasPlannedServings"], 2.0)
        self.assertTrue(entry[2]["hasPlannedConsumption"].startswith("QuantitySpecification:"))


if __name__ == "__main__":
    unittest.main()
