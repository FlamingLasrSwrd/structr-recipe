"""A recipe version's nutrition per serving, worked out once and stored (data-model.md Sec 18 J28;
mealplanner/recipe_nutrition.py, nutrition_scope.stored_figure).

The kitchen of tests/test_planning_extract.py, where each dish carries its own protein profile
(rule 7(a)): omelette 400 g at 12 g per 100 g over 2 servings is 24 g a serving, on sourced data;
pasta 300 g at 8 g over 2 is 12 g, on placeholder data; stew 500 g at 10 g over 2 is 25 g,
estimated. Soup's dish has no profile and its one ingredient none either, so it is unknown.
"""

import unittest
from unittest import mock

from mealplanner.nutrition_scope import AmbiguousProfileError, ServingFigure, serving_nutrient_figure, stored_figure
from mealplanner.planning.extract import build_problem
from mealplanner.recipe_nutrition import calculate, plans_using, schema_ready, stored_fields, targeted_nutrients
from tests.fakegraph import Ref, WritableGraph
from tests.planning_graph import add_recipe, add_target, add_type
from tests.test_planning_extract import DINNERS, NOW, kitchen

PLANS = ("omelette", "pasta", "stew", "soup")


def stocked():
    g = WritableGraph()
    g.nodes = kitchen().nodes
    add_recipe(g, "stew", output_grams=500, protein_per_100g=10, provenance="estimated", yield_servings=2, minutes=60)
    add_recipe(g, "soup", output_grams=600, protein_per_100g=5, provenance="sourced", yield_servings=3, minutes=40,
               inputs=[("Leeks", 200.0)])
    g.nodes["soup (dish)"]["nutrientProfilesAbout"] = []
    add_target(g, "protein floor", 40, 140, weight=0.3)
    return g


def plan(g, name):
    return g.get_all("Plan", name)["result"]


def stored_rows(g, name):
    return [n for n in g.nodes.values() if n["type"] == "NutrientProfile" and getattr(n.get("servingOf"), "id", None) == name]


class Calculate(unittest.TestCase):
    def test_each_recipe_keeps_what_its_figure_works_out_to(self):
        g = stocked()
        report = calculate(g)
        self.assertEqual((report.plans, report.counts["created"]), (4, 4))
        for name in PLANS:
            worked = serving_nutrient_figure(g, plan(g, name), "Protein", "g", stored=False)
            kept = stored_figure(g, plan(g, name), "Protein", "g")
            self.assertEqual((kept.amount, kept.trusted, kept.estimated, kept.reason, kept.method),
                             (worked.amount, worked.trusted, worked.estimated, worked.reason, "stored"), name)
        self.assertEqual([stored_figure(g, plan(g, n), "Protein", "g").amount for n in PLANS], [24.0, 12.0, 25.0, None])
        (row,) = stored_rows(g, "omelette")
        self.assertEqual((row["name"], row["basis"], row["provenance"], row["unit"], row["forNutrient"].id),
                         ("omelette -- Protein per serving", "per_serving", "calculated", "g", "Protein"))
        self.assertEqual([r["provenance"] for n in ("pasta", "stew") for r in stored_rows(g, n)], ["placeholder", "estimated"])
        self.assertTrue(row["visibleToAuthenticatedUsers"] and not row["visibleToPublicUsers"])

    def test_a_second_run_changes_nothing(self):
        g = stocked()
        calculate(g)
        writes = (g.posts, g.patches)
        report = calculate(g)
        self.assertEqual(report.counts, {"created": 0, "changed": 0, "unchanged": 4, "deleted": 0})
        self.assertEqual((g.posts, g.patches), writes)

    def test_a_changed_figure_is_found_by_check_and_stored_again(self):
        g = stocked()
        calculate(g)
        g.nodes["profile omelette"]["amount"] = 15.0                      # 400 g x 15 / 100 / 2 = 30 g a serving
        self.assertEqual(stored_figure(g, plan(g, "omelette"), "Protein", "g").amount, 24.0)   # stale until worked out
        (difference,) = calculate(g, check=True).differences
        self.assertIn("omelette: Protein: stored 24", difference)
        self.assertIn("works out to 30", difference)
        self.assertEqual(calculate(g).counts["changed"], 1)
        self.assertEqual(stored_figure(g, plan(g, "omelette"), "Protein", "g").amount, 30.0)
        self.assertEqual(calculate(g, check=True).differences, [])

    def test_check_finds_a_figure_whose_trust_changed_though_its_amount_did_not(self):
        g = stocked()
        calculate(g)
        g.nodes["profile omelette"]["provenance"] = "placeholder"
        (difference,) = calculate(g, check=True).differences
        self.assertIn("stored 24 (trusted), works out to 24 (untrusted; a profile is placeholder or unmarked)", difference)
        calculate(g)
        self.assertFalse(stored_figure(g, plan(g, "omelette"), "Protein", "g").trusted)

    def test_check_finds_a_missing_figure_and_stores_nothing(self):
        g = stocked()
        report = calculate(g, check=True)
        self.assertEqual(len(report.differences), 4)
        self.assertTrue(all("stored nothing" in d for d in report.differences))
        self.assertEqual((g.posts, g.patches), (0, 0))

    def test_only_these_plans(self):
        g = stocked()
        self.assertEqual(calculate(g, ["pasta"]).plans, 1)
        self.assertEqual([n for n in PLANS if stored_rows(g, n)], ["pasta"])

    def test_a_few_recipes_are_read_node_by_node_and_many_with_the_whole_types_first(self):
        from mealplanner import recipe_nutrition
        g = stocked()
        for plan_ids, listed in ((["pasta"], False), (None, True), (["pasta"] * (recipe_nutrition.PREFETCH_ABOVE + 1), True)):
            with mock.patch.object(g, "get_all", wraps=g.get_all) as reads:
                calculate(g, plan_ids, check=True)
            whole = {c.args[0] for c in reads.call_args_list if len(c.args) == 1 and not c.kwargs.get("where")}
            self.assertEqual("NutrientProfile" in whole, listed, plan_ids)

    def test_a_figure_for_a_nutrient_no_target_is_about_is_deleted(self):
        g = stocked()
        calculate(g)
        del g.nodes["protein floor"]
        g.nodes["week"]["hasConstraint"] = []
        self.assertEqual(len(calculate(g, check=True).differences), 4)
        self.assertEqual(calculate(g).counts["deleted"], 4)
        self.assertEqual([n for n in PLANS if stored_rows(g, n)], [])

    def test_two_stored_for_one_nutrient_cannot_be_read_and_the_next_run_keeps_one(self):
        g = stocked()
        calculate(g)
        g.post("/structr/rest/NutrientProfile", {"name": "a second", "basis": "per_serving", "forNutrient": "Protein",
                                                 "servingOf": "omelette", "amount": 1.0, "unit": "g"})
        with self.assertRaises(AmbiguousProfileError):
            stored_figure(g, plan(g, "omelette"), "Protein", "g")
        self.assertEqual(calculate(g).counts["deleted"], 1)
        self.assertEqual(stored_figure(g, plan(g, "omelette"), "Protein", "g").amount, 24.0)

    def test_a_figure_is_kept_in_the_first_targets_unit_and_read_in_any_other(self):
        g = stocked()
        add_target(g, "a protein cap", None, 200000, unit="mg", strictness="soft")
        self.assertEqual(targeted_nutrients(g), {"Protein": ("Protein", "mg")})
        calculate(g)
        (row,) = stored_rows(g, "omelette")
        self.assertEqual((row["amount"], row["unit"]), (24000.0, "mg"))
        self.assertAlmostEqual(stored_figure(g, plan(g, "omelette"), "Protein", "g").amount, 24.0)
        self.assertIsNone(stored_figure(g, plan(g, "omelette"), "Protein", "IU").amount)

    def test_a_target_in_no_nutrient_unit_is_passed_over(self):
        g = stocked()
        add_target(g, "a protein in cups", 1, 2, unit="cup", strictness="soft")
        self.assertEqual(targeted_nutrients(g), {"Protein": ("Protein", "g")})

    def test_a_difference_at_the_last_digit_is_not_a_change(self):
        g = stocked()
        calculate(g)
        (row,) = stored_rows(g, "omelette")
        row["amount"] = 24.0 * (1 + 1e-13)                  # what a round trip through another number format may leave
        self.assertEqual(calculate(g).counts["changed"], 0)
        self.assertEqual(calculate(g, check=True).differences, [])
        row["amount"] = 24.0 * (1 + 1e-10)                  # relative to the figure: 2.4e-9 g is within 1e-9 of 24 g
        self.assertEqual((calculate(g, check=True).differences, calculate(g).counts["changed"]), ([], 0))
        row["amount"] = 24.0 * (1 + 1e-6)
        self.assertEqual(len(calculate(g, check=True).differences), 1)

    def test_check_finds_a_figure_that_became_unknown(self):
        g = stocked()
        calculate(g)
        g.nodes["profile omelette"]["amount"] = None                     # the dish's protein is no longer known
        (difference,) = calculate(g, check=True).differences
        self.assertIn("omelette: Protein: stored 24", difference)
        self.assertIn("works out to unknown", difference)

    def test_a_target_without_a_range_is_passed_over(self):
        g = stocked()
        g.add("NutritionTarget", "a rangeless target", "a rangeless target", forNutrient=Ref("Protein"))
        self.assertEqual(targeted_nutrients(g), {"Protein": ("Protein", "g")})

    def test_a_profile_of_another_basis_on_a_plan_is_not_its_figure(self):
        g = stocked()
        g.post("/structr/rest/NutrientProfile", {"name": "odd", "basis": "per_100g", "forNutrient": "Protein",
                                                 "servingOf": "omelette", "amount": 1.0, "unit": "g"})
        self.assertIsNone(stored_figure(g, plan(g, "omelette"), "Protein", "g"))

    def test_the_schema_is_ready_once_the_relationship_exists(self):
        g = stocked()
        self.assertFalse(schema_ready(g))
        g.add("SchemaRelationshipNode", "rel", "rel", relationshipType="SERVING_OF")
        self.assertTrue(schema_ready(g))


class PlansUsing(unittest.TestCase):
    """Which recipes a change to foods sends to be worked out again (tools/import_vocabulary.py):
    omelette uses Eggs, pasta Noodles and Eggs, soup Leeks; each makes its own dish."""

    def test_the_recipes_using_a_food(self):
        g = stocked()
        self.assertEqual(plans_using(g, {"Eggs"}), ["omelette", "pasta"])
        self.assertEqual(plans_using(g, {"Leeks", "Noodles"}), ["pasta", "soup"])

    def test_and_those_using_a_food_below_it_whose_defaults_it_holds(self):
        g = stocked()
        add_type(g, "Animal foods")
        g.nodes["Eggs"]["parent"] = Ref("Animal foods")
        g.nodes["Animal foods"]["children"].append(Ref("Eggs"))
        self.assertEqual(plans_using(g, {"Animal foods"}), ["omelette", "pasta"])
        self.assertEqual(plans_using(g, {"Eggs"}), ["omelette", "pasta"])

    def test_an_output_counts_as_an_input_does(self):
        self.assertEqual(plans_using(stocked(), {"stew (dish)"}), ["stew"])

    def test_a_specification_about_nothing_is_no_use_of_a_food(self):
        g = stocked()
        g.add("Specification", "in9 pasta", hasParticipationRole="input", isOptional=False)          # specifies nothing
        g.nodes["step pasta"]["hasSpecification"].append(Ref("in9 pasta"))
        self.assertEqual((plans_using(g, {"Leeks"}), plans_using(g, {"Eggs"})), (["soup"], ["omelette", "pasta"]))

    def test_no_change_or_an_unused_food_sends_none(self):
        g = stocked()
        add_type(g, "Basil")
        self.assertEqual((plans_using(g, set()), plans_using(g, {"Basil"})), ([], []))


class StoredFields(unittest.TestCase):
    def test_every_kind_of_figure_reads_back_as_it_was(self):
        figures = [
            ServingFigure(24.0, True, "ingredients"),
            ServingFigure(24.0, True, "dish"),
            ServingFigure(25.0, True, "ingredients", "a profile is estimated", ("Leeks",), True),
            ServingFigure(12.0, False, "dish", "a profile is placeholder or unmarked"),
            ServingFigure(None, False, "ingredients", "ingredient 'Leeks' has no profile for this nutrient"),
        ]
        self.assertEqual([stored_fields(f, "g")["provenance"] for f in figures],
                         ["calculated", "calculated", "estimated", "placeholder", "calculated"])
        self.assertEqual(stored_fields(figures[1], "g")["source"], "worked out from the dish's own profiles")
        for i, figure in enumerate(figures):
            g = WritableGraph()
            add_type(g, "Protein")
            g.add("Plan", "p", "p")
            fields = {k: v for k, v in stored_fields(figure, "g").items() if v is not None}
            g.post("/structr/rest/NutrientProfile", {"name": "p -- Protein per serving", "basis": "per_serving",
                                                     "forNutrient": "Protein", "servingOf": "p", **fields})
            back = stored_figure(g, plan(g, "p"), "Protein", "g")
            self.assertEqual((back.amount, back.trusted, back.estimated, back.reason),
                             (figure.amount, figure.trusted, figure.estimated, figure.reason), i)


class ThePlannerReadsThem(unittest.TestCase):
    def candidates(self, p):
        return {cid: (c.nutrients, c.untrusted, c.estimated if hasattr(c, "estimated") else None)
                for cid, c in p.candidates.items()}

    def test_the_same_week_from_stored_figures_without_reading_a_foods_profiles(self):
        g = stocked()
        worked = build_problem(g, "week", DINNERS, NOW)
        calculate(g)
        with mock.patch.object(g, "get_all", wraps=g.get_all) as reads:
            kept = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(self.candidates(kept), self.candidates(worked))
        self.assertEqual(kept.notes, worked.notes)
        listings = [c for c in reads.call_args_list if c.args[0] == "NutrientProfile" and len(c.args) == 1]
        self.assertEqual([c.kwargs.get("where") for c in listings], [{"basis": "per_serving"}])
        self.assertFalse([c for c in reads.call_args_list if c.args[:1] == ("NutrientProfile",) and len(c.args) > 1
                          and c.args[1] and c.args[1].startswith("profile ")])

    def test_a_recipe_without_them_is_worked_out_and_named(self):
        g = stocked()
        calculate(g)
        add_recipe(g, "curry", output_grams=800, protein_per_100g=6, provenance="sourced", yield_servings=4, minutes=50)
        p = build_problem(g, "week", DINNERS, NOW)
        self.assertEqual(p.candidates["curry"].nutrients, {"Protein": 12.0})
        (note,) = [n for n in p.notes if "no stored figure" in n]
        self.assertIn("1 recipe(s)", note)
        self.assertIn("curry", note)

    def test_nothing_is_said_where_nothing_is_stored(self):
        self.assertFalse([n for n in build_problem(stocked(), "week", DINNERS, NOW).notes if "stored" in n])


if __name__ == "__main__":
    unittest.main()
