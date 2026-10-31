"""tools/check_source_energy.py: each recipe's energy per serving against the figure its source prints.
The stew fixture's energy is worked out by hand in tests/test_nutrition_derivation.py: 333 kcal a serving."""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from tests.fakegraph import Ref
from tests.test_nutrition_derivation import kitchen, spec


def load():
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "check_source_energy.py")
    spec_ = importlib.util.spec_from_file_location("check_source_energy_tool", path)
    module = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(module)
    return module


def doc(plan_name, kcal):
    return SimpleNamespace(plan_name=plan_name, source_kcal=kcal)


def graph():
    """The stew, named as a recipe's first version, and a second recipe whose beef has no amount, so its
    energy is unknown (J18)."""
    g = kitchen()
    g.nodes["stew"]["name"] = "Beef Stew v1"
    g.add("Step", "mystery step", hasSpecification=[spec(g, "in some beef", "input", "Beef"), spec(g, "out m", "output", "Stew")])
    g.add("QuantitySpecification", "m yield", value=2.0, unit="servings")
    g.add("Plan", "mystery", "Mystery v1", steps=[Ref("mystery step")], hasRecipeYield=Ref("m yield"))
    g.wait_until_ready = lambda: None
    return g


RECIPE = """name = "{name}"
servings = 4
meal_types = ["Dinner"]
{kcal}
[[steps]]
inputs = [{{ food = "Beef", amount = 500, unit = "g" }}]
"""


class Compare(unittest.TestCase):
    tool = load()

    def test_the_figure_against_the_source(self):
        (row,) = self.tool.compare(graph(), [doc("Beef Stew v1", 300)])
        self.assertAlmostEqual(row.kcal, 333.0)
        self.assertAlmostEqual(row.off, 0.11)                 # 333 / 300 - 1

    def test_worked_out_afresh_not_read_from_what_is_stored(self):
        """A stored figure goes stale until a tool works it out again (J28); the check is of the recipe now."""
        g = graph()
        g.add("NutrientProfile", "stale", basis="per_serving", forNutrient=Ref("Energy"), amount=999.0, unit="kcal",
              provenance="calculated", servingOf=Ref("stew"))
        g.nodes["stew"]["servingProfiles"] = [Ref("stale")]
        (row,) = self.tool.compare(g, [doc("Beef Stew v1", 300)])
        self.assertAlmostEqual(row.kcal, 333.0)

    def test_not_loaded_and_unknown_say_why(self):
        missing, unknown = self.tool.compare(graph(), [doc("Lamb Stew v1", 300), doc("Mystery v1", 300)])
        self.assertEqual((missing.kcal, missing.off, missing.why), (None, None, "not loaded"))
        self.assertIsNone(unknown.kcal)
        self.assertTrue(unknown.why)

    def test_two_plans_of_one_name_are_not_guessed_between(self):
        g = graph()
        g.add("Plan", "stew again", "Beef Stew v1", steps=[Ref("braise")], hasRecipeYield=Ref("yield"))
        (row,) = self.tool.compare(g, [doc("Beef Stew v1", 300)])
        self.assertEqual((row.kcal, row.why), (None, "2 Plans of that name"))

    def test_no_energy_nutrient_is_a_problem(self):
        g = graph()
        g.nodes["Energy"]["name"] = "Calories"
        with self.assertRaises(LookupError):
            self.tool.compare(g, [doc("Beef Stew v1", 300)])

    def test_the_summary(self):
        Row = self.tool.Row
        rows = [Row("a", 100, 110), Row("b", 100, 80), Row("c", 100, 150), Row("d", 100, None, "not loaded")]
        # distances 10%, 20%, 50%: median 20%; 10% within 15%; 10% and 20% within 30%
        self.assertEqual(self.tool.summary(rows), "3 of 4 worked out: median 20% from the source, 1 within 15%, 2 within 30%")


class Main(unittest.TestCase):
    tool = load()

    def run_on(self, recipes, *flags):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for k, (name, kcal) in enumerate(recipes):
                path = os.path.join(folder, f"r{k}.toml")
                with open(path, "w") as fh:
                    fh.write(RECIPE.format(name=name, kcal="" if kcal is None else f"source_kcal = {kcal}"))
                paths.append(path)
            out = io.StringIO()
            with mock.patch.object(self.tool, "connect", return_value=graph()), redirect_stdout(out):
                code = self.tool.main([*paths, *flags])
        return code, out.getvalue()

    def test_known_figures_pass_and_a_file_without_one_is_skipped(self):
        code, out = self.run_on([("Beef Stew", 300), ("Beef Stew", None)])
        self.assertEqual(code, 0)
        self.assertIn("+11%", out)
        self.assertIn("gives no source_kcal", out)

    def test_over_a_tolerance_fails(self):
        self.assertEqual(self.run_on([("Beef Stew", 300)], "--over", "10")[0], 1)
        self.assertEqual(self.run_on([("Beef Stew", 300)], "--over", "15")[0], 0)

    def test_a_recipe_not_loaded_or_unknown_fails(self):
        self.assertEqual(self.run_on([("Lamb Stew", 300)])[0], 1)
        self.assertEqual(self.run_on([("Mystery", 300)])[0], 1)


if __name__ == "__main__":
    unittest.main()
