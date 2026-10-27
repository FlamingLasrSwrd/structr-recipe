"""What may stand in for an ingredient (data-model.md Sec 5.3, J36): parsed with every problem named,
written as SubstitutionRules on the ingredient's Specification, and read back as the file says it."""

import tomllib
import unittest

from mealplanner.recipe_import import (
    RecipeFormatError, RecipeResolutionError, Substitute, export_plan, import_recipe, parse_recipe,
)
from tests.fakegraph import Ref
from tests.test_recipe_step_facts import kitchen

FILE = """
name = "Buttered Rice"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "toss"
inputs = [
  { food = "Rice", amount = 150, unit = "g" },
  { food = "Butter", amount = 3, unit = "tbsp", substitutes = [{ food = "Margarine" }, { food = "Olive Oil", ratio = 0.75 },
                                                               { food = "Lard", never = true }] },
]
"""


def data(**butter):
    d = tomllib.loads(FILE)
    d["steps"][0]["inputs"][1].update(butter)
    return d


def problems(d) -> list[str]:
    try:
        parse_recipe(d)
    except RecipeFormatError as exc:
        return exc.problems
    raise AssertionError("parsed")


def pantry():
    g = kitchen()
    for food in ("Butter", "Margarine", "Olive Oil", "Lard"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), nutrientProfilesAbout=[], defaultSpecifications=[])
    for kind in ("Density", "MassPerUnit"):                  # what converting a tbsp to grams looks up (none resolves)
        g.add("DomainType", kind, kind)
    return g


class Parse(unittest.TestCase):
    def test_substitutes_as_the_file_says_them(self):
        butter = parse_recipe(data()).steps[0].inputs[1]
        self.assertEqual(butter.substitutes, (Substitute("Margarine"), Substitute("Olive Oil", 0.75), Substitute("Lard", never=True)))
        self.assertEqual(parse_recipe(data()).steps[0].inputs[0].substitutes, ())

    def test_what_is_refused(self):
        cases = {
            "a number above 0": data(substitutes=[{"food": "Margarine", "ratio": 0}]),
            "cannot stand in for itself": data(substitutes=[{"food": "Butter"}]),
            "a substitute is listed twice": data(substitutes=[{"food": "Margarine"}, {"food": "Margarine", "ratio": 2}]),
            "unknown key 'brand'": data(substitutes=[{"food": "Margarine", "brand": "x"}]),
            "never must be true or false": data(substitutes=[{"food": "Lard", "never": "yes"}]),
            "substitutes must be a list": data(substitutes={"food": "Margarine"}),
        }
        for fragment, d in cases.items():
            self.assertTrue(any(fragment in p for p in problems(d)), (fragment, problems(d)))

    def test_nothing_stands_in_for_what_an_earlier_step_made(self):
        d = tomllib.loads(FILE)
        d["steps"] = [{"name": "cook", "makes": "Rice (cooked)", "inputs": [{"food": "Rice", "amount": 150, "unit": "g"}]},
                      {"name": "serve", "inputs": [{"food": "Rice (cooked)", "substitutes": [{"food": "Margarine"}]}]}]
        self.assertTrue(any("made by an earlier step, so nothing stands in for it" in p for p in problems(d)))


class Load(unittest.TestCase):
    def test_loaded_and_read_back_and_an_edit_leaves_nothing_behind(self):
        g, doc = pantry(), parse_recipe(data())
        report = import_recipe(g, doc)
        self.assertEqual(export_plan(g, report.plan_id), doc.plan_part())
        self.assertEqual(report.without_profiles, ["Rice", "Butter"])           # a substitute is not an ingredient eaten
        rule = g.nodes["SubstitutionRule:Buttered Rice v1 step 1 input 2 Butter or 2 Olive Oil"]
        self.assertEqual((rule["candidateType"].id, rule["substitutionRatio"], rule["isExcluded"]), ("Olive Oil", 0.75, False))
        self.assertTrue(import_recipe(g, doc).plan_unchanged)
        edited = parse_recipe(data(substitutes=[{"food": "Olive Oil", "ratio": 0.75}]))
        import_recipe(g, edited)
        self.assertEqual(export_plan(g, report.plan_id), edited.plan_part())
        self.assertEqual(sorted(n["name"] for n in g.nodes.values() if n["type"] == "SubstitutionRule"),
                         ["Buttered Rice v1 step 1 input 2 Butter or 1 Olive Oil"])

    def test_a_removed_ingredient_takes_its_rules_with_it(self):
        g = pantry()
        import_recipe(g, parse_recipe(data()))
        d = data()
        d["steps"][0]["inputs"] = d["steps"][0]["inputs"][:1]
        import_recipe(g, parse_recipe(d))
        self.assertEqual([n for n in g.nodes.values() if n["type"] == "SubstitutionRule"], [])

    def test_a_substitute_must_be_a_food_in_the_vocabulary(self):
        g = pantry()
        del g.nodes["Lard"]
        with self.assertRaises(RecipeResolutionError) as caught:
            import_recipe(g, parse_recipe(data()))
        self.assertTrue(any("substitute 'Lard'" in p for p in caught.exception.problems))


if __name__ == "__main__":
    unittest.main()
