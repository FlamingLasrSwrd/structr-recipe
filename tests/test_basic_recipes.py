"""The basic recipe set shipped with the repository (data/recipes/): every file loads by the recipe
format's rules and names only what data/vocabulary.toml holds, so `tools/import_recipe.py
data/recipes/*.toml` cannot stop on a name, and the set stays the representative mix it was chosen as."""

import collections
import glob
import os
import tomllib
import unittest

from mealplanner.meal_type_schema import MEAL_TYPES
from mealplanner.recipe_import import read_recipe

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = sorted(glob.glob(os.path.join(ROOT, "data", "recipes", "*.toml")))
SOURCES = ("https://www.nhlbi.nih.gov/sites/default/files/publications/",)   # US government works


def vocabulary():
    with open(os.path.join(ROOT, "data", "vocabulary.toml"), "rb") as fh:
        v = tomllib.load(fh)
    return ({f["name"] for f in v["food"]}, {m["name"] for m in v["method"]},
            {e["name"] for e in v["equipment"]}, {c["name"] for c in v["capability"]})


class BasicRecipes(unittest.TestCase):
    def setUp(self):
        self.docs = [read_recipe(path) for path in FILES]

    def test_there_are_twenty(self):
        self.assertEqual(len(FILES), 20)

    def test_every_name_is_in_the_vocabulary(self):
        foods, methods, equipment, capabilities = vocabulary()
        missing = []
        for doc in self.docs:
            made = set()
            for step in doc.steps:
                for ingredient in step.inputs:
                    if ingredient.food not in foods and ingredient.food not in made:
                        missing.append((doc.name, "food", ingredient.food))
                    for sub in ingredient.substitutes:
                        if sub.food not in foods:
                            missing.append((doc.name, "substitute", sub.food))
                if step.method and step.method not in methods:
                    missing.append((doc.name, "method", step.method))
                for tool in step.equipment:
                    known = capabilities if tool in step.capabilities else equipment
                    if tool not in known:
                        missing.append((doc.name, "capability" if tool in step.capabilities else "tool", tool))
                made.add(step.makes)
            for meal in doc.meal_types:
                if meal not in MEAL_TYPES:
                    missing.append((doc.name, "meal type", meal))
        self.assertEqual(missing, [])

    def test_each_names_its_public_domain_source(self):
        self.assertEqual([d.name for d in self.docs if not (d.source or "").startswith(SOURCES)], [])

    def test_the_mix_is_the_one_chosen(self):
        """5 breakfasts, 5 lunches, 8 dinners and 2 snacks, counting each recipe by its first meal type;
        at least a third with no meat or fish, by the ingredients' own names."""
        first = collections.Counter(d.meal_types[0] for d in self.docs)
        self.assertEqual(dict(first), {"Breakfast": 5, "Lunch": 5, "Dinner": 8, "Snack": 2})
        meaty = ("chicken", "beef", "pork", "salmon", "tuna", "sirloin", "bavette", "turkey", "fish", "shrimp")
        meatless = [d for d in self.docs
                    if not any(any(m in i.food.lower() for m in meaty) for s in d.steps for i in s.inputs)]
        self.assertGreaterEqual(len(meatless) * 3, len(self.docs))


if __name__ == "__main__":
    unittest.main()
