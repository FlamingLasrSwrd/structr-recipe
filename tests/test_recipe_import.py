"""Recipe files: parsing (every problem reported at once), name resolution, and reading a Plan back.

Writing to Structr is exercised against a real instance by scripts/29b_recipe_import_demo.py."""

import tomllib
import unittest

from mealplanner.recipe_import import (
    Ingredient, RecipeFormatError, RecipeResolutionError, StepDoc, export_plan, parse_recipe, resolve,
)
from tests.fakegraph import FakeGraph, Ref

GOOD = """
name = "Garlic Butter Noodles"
source = "https://example.org/noodles"
servings = 4
minutes = 25
difficulty = "easy"
meal_types = ["Dinner", "Lunch"]

[[steps]]
name = "boil the noodles"
method = "Boiling"
makes = "Noodles (cooked)"
inputs = [{ food = "Noodles (dry)", amount = 400, unit = "g" }]

[[steps]]
name = "toss"
equipment = ["Wok", "Tongs"]
inputs = [
  { food = "Noodles (cooked)" },
  { food = "Butter", amount = 3, unit = "tbsp" },
  { food = "Garlic", amount = 4, unit = "each" },
  { food = "Salt" },
  { food = "Parsley", amount = 5, unit = "g", optional = true },
]
"""


def good(**changes):
    data = tomllib.loads(GOOD)
    data.update(changes)
    return data


class Parse(unittest.TestCase):
    def test_a_good_file(self):
        doc = parse_recipe(good())
        self.assertEqual((doc.name, doc.version, doc.servings, doc.minutes, doc.difficulty, doc.meal_types),
                         ("Garlic Butter Noodles", 1, 4.0, 25.0, "easy", ("Dinner", "Lunch")))
        self.assertEqual(doc.dish, "Garlic Butter Noodles")
        self.assertEqual(doc.plan_name, "Garlic Butter Noodles v1")
        first, second = doc.steps
        self.assertEqual((first.label, first.method, first.makes), ("boil the noodles", "Boiling", "Noodles (cooked)"))
        self.assertEqual((second.method, second.equipment, first.equipment), (None, ("Wok", "Tongs"), ()))
        self.assertEqual(second.inputs[0], Ingredient("Noodles (cooked)"))
        self.assertEqual(second.inputs[1], Ingredient("Butter", 3.0, "tbsp"))
        self.assertEqual(second.inputs[4], Ingredient("Parsley", 5.0, "g", True))

    def problems(self, data):
        with self.assertRaises(RecipeFormatError) as caught:
            parse_recipe(data)
        return caught.exception.problems

    def test_every_problem_is_reported_at_once(self):
        data = good(servings=0, colour="red", difficulty="tricky")
        data["steps"][0]["inputs"][0]["unit"] = "handful"
        problems = self.problems(data)
        self.assertEqual(len(problems), 4, problems)
        for fragment in ("unknown key 'colour'", "servings", "difficulty", "'handful'"):
            self.assertTrue(any(fragment in p for p in problems), fragment)

    def test_amount_and_unit_come_together(self):
        data = good()
        data["steps"][1]["inputs"][1] = {"food": "Butter", "amount": 3}
        data["steps"][1]["inputs"][2] = {"food": "Garlic", "unit": "each"}
        problems = self.problems(data)
        self.assertTrue(any("unit None" in p for p in problems))
        self.assertTrue(any("a unit without an amount" in p for p in problems))

    def test_a_name_that_could_never_be_found_again(self):
        self.assertTrue(any("','" in p for p in self.problems(good(name="Rice, Beans"))))

    def test_a_recipe_needs_a_meal_type(self):
        self.assertTrue(any("meal_types" in p for p in self.problems(good(meal_types=[]))))

    def test_a_baseline_is_a_day_of_it_and_no_meal(self):
        data = good(baseline=True, servings=1)
        del data["meal_types"]
        doc = parse_recipe(data)
        self.assertEqual((doc.meal_types, doc.servings), ((), 1.0))
        self.assertTrue(any("no meal_types" in p for p in self.problems(good(baseline=True, servings=1))))
        del data["servings"]
        self.assertTrue(any("servings" in p for p in self.problems(dict(data, servings=2))))
        self.assertTrue(any("true or false" in p for p in self.problems(good(baseline="yes"))))

    def test_only_the_last_step_may_leave_out_makes(self):
        data = good()
        del data["steps"][0]["makes"]
        self.assertTrue(any("only the last step" in p for p in self.problems(data)))

    def test_an_intermediate_must_be_used_later(self):
        data = good()
        data["steps"][1]["inputs"][0] = {"food": "Noodles (dry)", "amount": 1, "unit": "g"}
        self.assertTrue(any("which no later step uses" in p for p in self.problems(data)))

    def test_nothing_is_used_before_it_is_made(self):
        data = good()
        data["steps"][0]["inputs"].append({"food": "Garlic Butter Noodles"})
        self.assertTrue(any("made at or after it" in p for p in self.problems(data)))

    def test_a_tool_listed_twice(self):
        data = good()
        data["steps"][1]["equipment"] = ["Wok", "Wok"]
        self.assertTrue(any("listed twice" in p for p in self.problems(data)))

    def test_the_last_step_makes_the_dish(self):
        data = good(dish="Noodle Bowl")
        data["steps"][1]["makes"] = "Something Else"
        self.assertTrue(any("makes the dish 'Noodle Bowl'" in p for p in self.problems(data)))


def vocabulary():
    g = FakeGraph()
    for hid in ("Food Identity", "Transformation Method", "Nutrient", "Equipment Type"):
        g.add("TypeHierarchy", hid, hid)
    for tool in ("Wok", "Tongs"):
        g.add("DomainType", tool, tool, hierarchy=Ref("Equipment Type"))
    for food in ("Noodles (dry)", "Butter", "Garlic", "Salt", "Parsley"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), nutrientProfilesAbout=[])
    g.add("DomainType", "Boiling", "Boiling", hierarchy=Ref("Transformation Method"))
    g.add("DomainType", "Protein", "Protein", hierarchy=Ref("Nutrient"))
    g.add("ConceptScheme", "Meal Type", "Meal Type")
    g.add("ConceptScheme", "Identifier Scheme", "Identifier Scheme")
    for meal in ("Dinner", "Lunch"):
        g.add("Concept", meal, meal, inScheme=Ref("Meal Type"))
    g.add("Concept", "Web page", "Web page", inScheme=Ref("Identifier Scheme"))
    return g


class Resolve(unittest.TestCase):
    def test_every_name_resolves_and_new_products_are_marked(self):
        names = resolve(vocabulary(), parse_recipe(good()))
        self.assertEqual(set(names.foods), {"Noodles (dry)", "Butter", "Garlic", "Salt", "Parsley"})
        self.assertEqual(names.products, {"Noodles (cooked)": None, "Garlic Butter Noodles": None})
        self.assertEqual((names.methods, names.web_page), ({"Boiling": "Boiling"}, "Web page"))
        self.assertEqual(names.equipment, {"Wok": "Wok", "Tongs": "Tongs"})

    def test_every_missing_name_is_listed_before_anything_is_written(self):
        g = vocabulary()
        del g.nodes["Garlic"], g.nodes["Boiling"], g.nodes["Lunch"], g.nodes["Tongs"]
        with self.assertRaises(RecipeResolutionError) as caught:
            resolve(g, parse_recipe(good()))
        problems = caught.exception.problems
        self.assertEqual(len(problems), 4, problems)
        for fragment in ("ingredient 'Garlic'", "method 'Boiling'", "meal type 'Lunch'", "equipment 'Tongs'"):
            self.assertTrue(any(fragment in p for p in problems), fragment)

    def test_a_food_must_be_a_food(self):
        data = good()
        data["steps"][1]["inputs"][3] = {"food": "Protein"}          # a Nutrient, not a Food-Identity Type
        with self.assertRaises(RecipeResolutionError) as caught:
            resolve(vocabulary(), parse_recipe(data))
        self.assertIn("not in the right hierarchy", caught.exception.problems[0])

    def test_an_existing_product_type_is_reused(self):
        g = vocabulary()
        g.add("DomainType", "Noodles (cooked)", "Noodles (cooked)", hierarchy=Ref("Food Identity"))
        self.assertEqual(resolve(g, parse_recipe(good())).products["Noodles (cooked)"], "Noodles (cooked)")

    def test_a_meal_type_must_be_in_the_meal_type_scheme(self):
        g = vocabulary()
        g.nodes["Lunch"]["inScheme"] = Ref("Identifier Scheme")
        with self.assertRaises(RecipeResolutionError):
            resolve(g, parse_recipe(good()))

    def test_a_source_needs_the_web_page_scheme(self):
        g = vocabulary()
        del g.nodes["Web page"]
        with self.assertRaises(RecipeResolutionError) as caught:
            resolve(g, parse_recipe(good()))
        self.assertIn("'Web page'", caught.exception.problems[0])


class ReadBack(unittest.TestCase):
    """export_plan reads a Plan written with the loader's naming back into the file's shape. The graph
    here is built by hand from the naming scheme, not by the loader."""

    def build(self, plan_name):
        g = FakeGraph()
        g.add("QuantitySpecification", "yield", value=2.0, unit="servings")
        g.add("DomainType", "Rice", "Rice")
        g.add("DomainType", "Rice (cooked)", "Rice (cooked)")
        g.add("DomainType", "Bowl", "Bowl")
        g.add("DomainType", "Boiling", "Boiling")
        g.add("QuantitySpecification", "q", value=1.5, unit="cup")
        # Created out of order on purpose: the reader must order by the numbers in the names.
        g.add("Specification", "s2i1", f"{plan_name} step 2 input 1 Rice (cooked)", hasParticipationRole="input",
              specifies=Ref("Rice (cooked)"), isOptional=False)
        g.add("Specification", "s2o", f"{plan_name} step 2 output Bowl", hasParticipationRole="output",
              specifies=Ref("Bowl"), isOptional=False)
        g.add("Specification", "s1i1", f"{plan_name} step 1 input 1 Rice", hasParticipationRole="input",
              specifies=Ref("Rice"), hasSpecifiedQuantity=Ref("q"), isOptional=False)
        g.add("Specification", "s1o", f"{plan_name} step 1 output Rice (cooked)", hasParticipationRole="output",
              specifies=Ref("Rice (cooked)"), isOptional=False)
        g.add("DomainType", "Bowl rack", "Bowl rack")
        g.add("DomainType", "Ladle", "Ladle")
        g.add("Specification", "s2e2", f"{plan_name} step 2 equipment 2 Bowl rack", hasParticipationRole="instrument",
              specifies=Ref("Bowl rack"), isOptional=False)
        g.add("Specification", "s2e1", f"{plan_name} step 2 equipment 1 Ladle", hasParticipationRole="instrument",
              specifies=Ref("Ladle"), isOptional=False)
        g.add("Step", "st2", f"{plan_name} step 2 -- serve",
              hasSpecification=[Ref("s2e2"), Ref("s2o"), Ref("s2i1"), Ref("s2e1")])
        g.add("Step", "st1", f"{plan_name} step 1 -- boil -- well", instanceOf=Ref("Boiling"),
              hasSpecification=[Ref("s1o"), Ref("s1i1")])
        g.add("Plan", "plan", plan_name, steps=[Ref("st2"), Ref("st1")], hasRecipeYield=Ref("yield"),
              estimatedDurationMinutes=None, difficultyRating="easy")
        return g

    def test_a_plan_reads_back_in_the_files_shape(self):
        for plan_name in ("Bowl v1", "TEST -- Bowl v1"):
            self.assertEqual(export_plan(self.build(plan_name), "plan"), (2.0, None, "easy", (
                StepDoc("boil -- well", "Boiling", (Ingredient("Rice", 1.5, "cup"),), "Rice (cooked)"),
                StepDoc("serve", None, (Ingredient("Rice (cooked)"),), "Bowl", ("Ladle", "Bowl rack")),
            )))


if __name__ == "__main__":
    unittest.main()
