"""What a recipe needs that a kitchen lacks (mealplanner/kitchen_check.py), and how the importer asks.

The graph: equipment types Pan > Skillet > Cast-iron skillet, Oven > Convection oven, Wok, Broiler;
capabilities Heating > Oven heat (borne by Oven) and Heating > Broiler heat (borne by Broiler).
The kitchen holds one Skillet and one Convection oven. Every expected answer below is read off that
by hand."""

import importlib.util
import os
import unittest
from unittest import mock

from mealplanner import kitchen_check
from mealplanner.recipe_import import StepDoc
from tests.fakegraph import FakeGraph, Ref


def graph(members=("Skillet", "Convection oven")):
    g = FakeGraph()

    def dtype(name, parent=None, children=(), borne_by=()):
        g.add("DomainType", name, parent=Ref(parent) if parent else None, children=[Ref(c) for c in children],
              functionBorneBy=[Ref(b) for b in borne_by])

    dtype("Pan", children=["Skillet"])
    dtype("Skillet", parent="Pan", children=["Cast-iron skillet"])
    dtype("Cast-iron skillet", parent="Skillet")
    dtype("Oven", children=["Convection oven"])
    dtype("Convection oven", parent="Oven")
    dtype("Wok")
    dtype("Broiler")
    dtype("Heating", children=["Oven heat", "Broiler heat"])
    dtype("Oven heat", parent="Heating", borne_by=["Oven"])
    dtype("Broiler heat", parent="Heating", borne_by=["Broiler"])
    for n, kind in enumerate(members):
        g.add("EquipmentObject", f"tool {n}", instanceOf=Ref(kind))
    g.add("UtensilSet", "TEST -- kitchen", hasMemberPart=[Ref(f"tool {n}") for n in range(len(members))])
    return g


EQUIPMENT = {name: name for name in ("Pan", "Skillet", "Cast-iron skillet", "Oven", "Wok", "Broiler",
                                     "Heating", "Oven heat", "Broiler heat")}   # names are the ids here


def step(label, *needs, capabilities=()):
    return StepDoc(label, None, (), "it", tuple(needs), capabilities=tuple(capabilities))


def lacks(g, *steps):
    (kitchen,) = kitchen_check.kitchens(g)
    return [(m.step, m.need, m.capability) for m in kitchen_check.missing(g, steps, EQUIPMENT, kitchen)]


class Kitchens(unittest.TestCase):
    def test_a_kitchen_holds_its_members_types_and_every_type_above_them(self):
        (kitchen,) = kitchen_check.kitchens(graph())
        self.assertEqual(kitchen["name"], "TEST -- kitchen")
        self.assertEqual(kitchen["types"], {"Skillet", "Pan", "Convection oven", "Oven"})

    def test_an_instance_without_a_kitchen_has_none(self):
        g = FakeGraph()
        self.assertEqual(kitchen_check.kitchens(g), [])


class WhatIsMissing(unittest.TestCase):
    def test_a_tool_is_met_by_its_type_or_a_narrower_one(self):
        self.assertEqual(lacks(graph(), step("fry", "Skillet"), step("sear", "Pan")), [])

    def test_a_narrower_tool_than_the_kitchen_has_is_missing(self):
        self.assertEqual(lacks(graph(), step("sear", "Cast-iron skillet")), [("sear", "Cast-iron skillet", False)])

    def test_a_tool_of_another_kind_is_missing(self):
        self.assertEqual(lacks(graph(), step("stir-fry", "Wok", "Skillet")), [("stir-fry", "Wok", False)])

    def test_a_capability_is_met_by_a_tool_whose_type_or_a_type_above_it_gives_it(self):
        # the kitchen's Convection oven is an Oven, and an Oven gives Oven heat
        self.assertEqual(lacks(graph(), step("bake", "Oven heat", capabilities=["Oven heat"])), [])

    def test_a_broader_capability_is_met_by_a_tool_giving_a_narrower_one(self):
        self.assertEqual(lacks(graph(), step("heat", "Heating", capabilities=["Heating"])), [])

    def test_a_capability_no_tool_in_the_kitchen_gives_is_missing(self):
        self.assertEqual(lacks(graph(), step("broil", "Broiler heat", capabilities=["Broiler heat"])),
                         [("broil", "Broiler heat", True)])

    def test_an_empty_kitchen_lacks_everything_in_step_order(self):
        got = lacks(graph(members=()), step("one", "Pan"), step("two", "Oven heat", "Wok", capabilities=["Oven heat"]))
        self.assertEqual(got, [("one", "Pan", False), ("two", "Oven heat", True), ("two", "Wok", False)])

    def test_the_description_says_which_step_and_what(self):
        self.assertEqual(kitchen_check.describe(kitchen_check.Missing("broil", "Broiler heat", True)),
                         "step 'broil': something that gives Broiler heat")
        self.assertEqual(kitchen_check.describe(kitchen_check.Missing("sear", "Wok", False)), "step 'sear': Wok")


_spec = importlib.util.spec_from_file_location(
    "import_recipe_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "import_recipe.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class Doc:
    plan_name = "TEST -- dish v1"
    steps = ()


class Imported:
    plan_unchanged = False
    plan_id = "plan"
    created_types = removed = unconvertible = without_profiles = ()
    foods = {}
    products = {}
    equipment = {}


class TheImporterAsks(unittest.TestCase):
    """tools/import_recipe.py's choices, with the graph's answers stood in for."""

    def run_tool(self, *argv, lacking=True, kitchens=({"name": "TEST -- kitchen", "types": frozenset()},),
                 unchanged=False, answer="", interactive=True):
        calls = {"imports": 0, "asked": 0}

        def import_recipe(client, doc, check_only=False):
            if not check_only:
                calls["imports"] += 1
            return Imported()

        def ask(prompt):
            calls["asked"] += 1
            return answer

        gaps = [kitchen_check.Missing("sear", "Wok", False)] if lacking else []
        with mock.patch.object(tool, "connect"), \
                mock.patch.object(tool, "read_recipe", return_value=Doc()), \
                mock.patch.object(tool, "import_recipe", side_effect=import_recipe), \
                mock.patch.object(tool, "loaded_unchanged", return_value=unchanged), \
                mock.patch.object(tool.kitchen_check, "kitchens", return_value=list(kitchens)), \
                mock.patch.object(tool.kitchen_check, "missing", return_value=gaps), \
                mock.patch.object(tool, "schema_ready", return_value=False), \
                mock.patch("builtins.print") as printed:
            code = tool.main(["dish.toml", *argv], ask=ask, interactive=interactive)
        out = "\n".join(" ".join(str(a) for a in c.args) for c in printed.call_args_list)
        return code, calls, out

    def test_a_yes_imports_it(self):
        code, calls, out = self.run_tool(answer="y")
        self.assertEqual((code, calls), (0, {"imports": 1, "asked": 1}))
        self.assertIn("missing in the kitchen 'TEST -- kitchen': step 'sear': Wok", out)

    def test_anything_but_a_yes_leaves_it_out_and_is_no_failure(self):
        for answer in ("", "n", "no", "maybe"):
            with self.subTest(answer=answer):
                code, calls, out = self.run_tool(answer=answer)
                self.assertEqual((code, calls), (0, {"imports": 0, "asked": 1}))
                self.assertIn("not imported", out)

    def test_with_no_one_to_ask_it_skips_the_recipe_reports_it_and_fails_the_run(self):
        code, calls, out = self.run_tool(interactive=False, answer="y")
        self.assertEqual((code, calls), (1, {"imports": 0, "asked": 0}))
        self.assertIn("skipped", out)

    def test_check_only_reports_and_never_asks(self):
        code, calls, out = self.run_tool("--check")
        self.assertEqual((code, calls), (0, {"imports": 0, "asked": 0}))
        self.assertIn("missing in the kitchen", out)

    def test_a_recipe_loaded_unchanged_is_reported_not_asked_about(self):
        code, calls, out = self.run_tool(unchanged=True)
        self.assertEqual((code, calls), (0, {"imports": 1, "asked": 0}))
        self.assertIn("missing in the kitchen", out)

    def test_nothing_missing_nothing_asked(self):
        code, calls, out = self.run_tool(lacking=False)
        self.assertEqual((code, calls), (0, {"imports": 1, "asked": 0}))
        self.assertNotIn("missing", out)

    def test_without_a_kitchen_it_says_the_tools_were_not_checked_and_imports(self):
        code, calls, out = self.run_tool(kitchens=(), lacking=False)
        self.assertEqual((code, calls), (0, {"imports": 1, "asked": 0}))
        self.assertIn("no kitchen on this instance", out)


if __name__ == "__main__":
    unittest.main()
