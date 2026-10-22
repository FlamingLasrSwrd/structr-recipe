"""The tools that store a recipe's nutrition per serving (J28): tools/calculate_recipe_nutrition.py,
and tools/import_recipe.py and tools/import_vocabulary.py working it out again after a change."""

import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from mealplanner.recipe_nutrition import Report
from tests.test_recipe_nutrition import stocked, stored_rows


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_tool", os.path.join(os.path.dirname(__file__), "..", "tools", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(module, argv, client):
    client.wait_until_ready = lambda: None
    out = io.StringIO()
    with mock.patch.object(module, "connect", return_value=client), redirect_stdout(out):
        code = module.main(argv)
    return code, out.getvalue()


def ready(g):
    g.add("SchemaRelationshipNode", "rel", "rel", relationshipType="SERVING_OF")
    return g


class CalculateTool(unittest.TestCase):
    tool = load("calculate_recipe_nutrition")

    def test_it_stores_every_recipe_then_check_finds_nothing(self):
        g = ready(stocked())
        code, out = run(self.tool, [], g)
        self.assertEqual(code, 0)
        self.assertIn("4 recipe(s): created 4", out)
        self.assertEqual(run(self.tool, ["--check"], g)[0], 0)

    def test_check_fails_on_a_difference(self):
        g = ready(stocked())
        code, out = run(self.tool, ["--check"], g)
        self.assertEqual(code, 1)
        self.assertIn("4 difference(s)", out)

    def test_named_plans_only_and_an_unknown_name_is_refused(self):
        g = ready(stocked())
        self.assertEqual(run(self.tool, ["pasta"], g)[0], 0)
        self.assertEqual([n for n in ("omelette", "pasta") if stored_rows(g, n)], ["pasta"])
        code, out = run(self.tool, ["no such plan"], g)
        self.assertEqual(code, 1)
        self.assertIn("no single Plan named 'no such plan'", out)

    def test_an_instance_without_the_schema_is_told_what_to_run(self):
        code, out = run(self.tool, [], stocked())
        self.assertEqual(code, 1)
        self.assertIn("scripts/35a", out)


class ImportRecipeTool(unittest.TestCase):
    tool = load("import_recipe")

    def test_the_recipes_it_loads_are_worked_out_again(self):
        result = SimpleNamespace(plan_id="pasta", plan_unchanged=False, created_types=[], removed=[], unconvertible=[],
                                 without_profiles=[])
        doc = SimpleNamespace(plan_name="pasta")
        with mock.patch.object(self.tool, "read_recipe", return_value=doc), \
                mock.patch.object(self.tool, "import_recipe", return_value=result), \
                mock.patch.object(self.tool, "calculate", return_value=Report(plans=1)) as calc:
            code, out = run(self.tool, ["a.toml", "b.toml"], ready(stocked()))
        self.assertEqual(code, 0)
        self.assertEqual(calc.call_args.args[1], ["pasta", "pasta"])
        self.assertIn("recipe nutrition per serving:", out)

    def test_not_without_the_schema_nor_for_a_check(self):
        result = SimpleNamespace(plan_id="pasta", plan_unchanged=True, created_types=[], removed=[], unconvertible=[],
                                 without_profiles=[], foods={}, products={})
        doc = SimpleNamespace(plan_name="pasta")
        for argv, g in ((["a.toml"], stocked()), (["--check", "a.toml"], ready(stocked()))):
            with mock.patch.object(self.tool, "read_recipe", return_value=doc), \
                    mock.patch.object(self.tool, "import_recipe", return_value=result), \
                    mock.patch.object(self.tool, "calculate") as calc:
                run(self.tool, argv, g)
            calc.assert_not_called()


class ImportVocabularyTool(unittest.TestCase):
    tool = load("import_vocabulary")

    def run_with(self, counts, g):
        vocabulary = SimpleNamespace(foods=[], methods=[], equipment=[], fdc={"nutrients": []})
        with mock.patch.object(self.tool, "read_vocabulary", return_value=vocabulary), \
                mock.patch.object(self.tool, "import_vocabulary", return_value=counts), \
                mock.patch.object(self.tool, "calculate", return_value=Report(plans=4)) as calc:
            code, out = run(self.tool, [], g)
        self.assertEqual(code, 0)
        return calc, out

    def test_a_change_works_every_recipe_out_again(self):
        for changed in ({"created": 1}, {"changed": 1}, {"deleted": 1}):
            counts = {"created": 0, "changed": 0, "unchanged": 5, "deleted": 0, **changed}
            calc, out = self.run_with(counts, ready(stocked()))
            calc.assert_called_once()
            self.assertEqual(calc.call_args.args[1:], ())
            self.assertIn("recipe nutrition per serving, 4 recipe(s)", out)

    def test_no_change_or_no_schema_leaves_them(self):
        calc, _ = self.run_with({"created": 0, "changed": 0, "unchanged": 5, "deleted": 0}, ready(stocked()))
        calc.assert_not_called()
        calc, _ = self.run_with({"created": 1, "changed": 0, "unchanged": 5, "deleted": 0}, stocked())
        calc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
