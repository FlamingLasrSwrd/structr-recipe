"""mealplanner/instructions.py: a recipe's steps written as plain sentences of our own, from their facts.
Every expected sentence below is written out by hand."""

import unittest

from mealplanner.instructions import as_data, instructions, join, number
from mealplanner.recipe_import import Heat, Ingredient, StepDoc


def step(label="mix it", method=None, inputs=(Ingredient("Flour", 100.0, "g"),), makes="Dough", **facts):
    return StepDoc(label, method, tuple(inputs), makes, **facts)


class Words(unittest.TestCase):
    def test_numbers_as_the_javascript_writes_them(self):
        self.assertEqual([number(x) for x in (400.0, 1.5, 0.125, 0.0625, 2 / 3, 283.9056, 3.0)],
                         ["400", "1.5", "0.125", "0.063", "0.667", "283.906", "3"])

    def test_lists(self):
        self.assertEqual([join([]), join(["a"]), join(["a", "b"]), join(["a", "b", "c"])], ["", "a", "a and b", "a, b and c"])


class Sentences(unittest.TestCase):
    def test_a_method_gives_the_verb_and_a_step_without_one_its_label(self):
        self.assertEqual(instructions([step(method="Mixing")]), ["Mix 100 g flour."])
        self.assertEqual(instructions([step(label="knead well")]), ["Knead well: 100 g flour."])
        self.assertEqual(instructions([step(method="Searing", label="sear it")]), ["Sear 100 g flour."])

    def test_ingredients(self):
        made_first = step(label="boil", method="Boiling", inputs=(Ingredient("Noodles (dry)", 400.0, "g"),), makes="Noodles (cooked)")
        toss = step(label="toss", inputs=(Ingredient("Noodles (cooked)"), Ingredient("Butter", 3.0, "tbsp"), Ingredient("Garlic", 4.0, "each"),
                                          Ingredient("Salt", optional=True), Ingredient("Parsley", 5.0, "g", True)), makes="Noodles")
        self.assertEqual(instructions([made_first, toss]), [
            "Boil 400 g noodles (dry).",
            "Toss: the noodles (cooked), 3 tbsp butter, 4 garlic, salt, to taste and 5 g parsley (optional).",
        ])

    def test_tools_and_their_heat(self):
        self.assertEqual(instructions([step(method="Roasting", equipment=("Oven",), heat=(Heat("Oven", temp=220.0, unit="C"),))]),
                         ["Roast 100 g flour in the oven at 220 °C."])
        self.assertEqual(instructions([step(method="Sauteing", equipment=("Skillet", "Spatula"), heat=(Heat("Skillet", level="medium-high"),))]),
                         ["Sauté 100 g flour on the skillet over medium-high heat using the spatula."])
        self.assertEqual(instructions([step(method="Mixing", equipment=("Bowl", "Whisk"))]), ["Mix 100 g flour using the bowl and whisk."])

    def test_doneness(self):
        self.assertEqual(instructions([step(method="Baking", until="golden")]), ["Bake 100 g flour until golden."])
        self.assertEqual(instructions([step(method="Baking", until="until set")]), ["Bake 100 g flour until set."])
        self.assertEqual(instructions([step(method="Roasting", inside=(165.0, "F"))]), ["Roast 100 g flour until 165 °F inside."])
        self.assertEqual(instructions([step(method="Roasting", until="browned", inside=(74.0, "C"))]),
                         ["Roast 100 g flour until browned and 74 °C inside."])

    def test_times(self):
        self.assertEqual(instructions([step(method="Mixing", minutes=3.0)]), ["Mix 100 g flour, about 3 minutes."])
        self.assertEqual(instructions([step(method="Soaking", wait_minutes=480.0)]), ["Soak 100 g flour, about 480 minutes."])
        self.assertEqual(instructions([step(method="Baking", minutes=5.0, wait_minutes=25.0)]),
                         ["Bake 100 g flour, about 30 minutes, 5 of them hands-on."])
        self.assertEqual(instructions([step(method="Mixing", minutes=0.0)]), ["Mix 100 g flour."])

    def test_a_step_beside_the_one_before_it_says_meanwhile(self):
        first = step(label="boil the rice", method="Boiling", inputs=(Ingredient("Rice", 150.0, "g"),), makes="Rice (cooked)")
        beside = step(label="sear the fish", method="Searing", inputs=(Ingredient("Fish", 300.0, "g"),), makes="Fish (seared)", after=())
        both = step(label="plate", inputs=(Ingredient("Rice (cooked)"), Ingredient("Fish (seared)")), makes="Fish and Rice", after=(1, 2))
        self.assertEqual(instructions([first, beside, both]), [
            "Boil 150 g rice.",
            "Meanwhile, sear 300 g fish.",
            "Plate: the rice (cooked) and the fish (seared).",
        ])
        self.assertEqual(instructions([first, step(label="rest it", inputs=(Ingredient("Rice (cooked)"),), makes="Rice", after=(1,))]),
                         ["Boil 150 g rice.", "Rest it: the rice (cooked)."])

    def test_everything_at_once(self):
        roast = step(label="roast the chicken", method="Roasting", inputs=(Ingredient("Chicken", 300.0, "g"),), makes="Chicken (roasted)",
                     equipment=("Oven", "Tongs"), heat=(Heat("Oven", temp=425.0, unit="F"),), minutes=5.0, wait_minutes=25.0,
                     until="golden", inside=(165.0, "F"))
        self.assertEqual(instructions([roast]), [
            "Roast 300 g chicken in the oven at 425 °F using the tongs until golden and 165 °F inside, about 30 minutes, 5 of them hands-on."])


class AsData(unittest.TestCase):
    def test_plain_data_holds_every_fact(self):
        s = step(method="Roasting", equipment=("Oven",), heat=(Heat("Oven", temp=425.0, unit="F"),), minutes=5.0,
                 wait_minutes=25.0, after=(), until="golden", inside=(165.0, "F"))
        (d,) = as_data([s])
        self.assertEqual(d, {"label": "mix it", "method": "Roasting", "makes": "Dough", "equipment": ["Oven"],
                             "inputs": [{"food": "Flour", "amount": 100.0, "unit": "g", "optional": False}],
                             "heat": [{"tool": "Oven", "temp": 425.0, "unit": "F", "level": None}],
                             "minutes": 5.0, "wait_minutes": 25.0, "after": [], "until": "golden", "inside": [165.0, "F"]})


if __name__ == "__main__":
    unittest.main()
