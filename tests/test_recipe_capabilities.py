"""A tool named by what it does (data-model.md Sec 5, J37): a step's equipment may name a capability, a
Function type, instead of a tool. Parsed with every problem named, written as an instrument
Specification that specifies the capability, read back as the file says it, and met, in the
sentence, by every tool whose type can give it or one of its subtypes."""

import tomllib
import unittest

from mealplanner.instructions import instructions
from mealplanner.recipe_import import (
    Heat, RecipeFormatError, RecipeResolutionError, capability_bearers, export_plan, import_recipe, parse_recipe,
)
from tests.fakegraph import Ref
from tests.test_recipe_step_facts import kitchen

FILE = """
name = "Broiled Chicken"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "broil the chicken"
method = "Roasting"
equipment = ["Saucepan", { capability = "Broiler heat", heat = "high" }]
inputs = [{ food = "Chicken", amount = 300, unit = "g" }]
"""


def data(*equipment):
    d = tomllib.loads(FILE)
    if equipment:
        d["steps"][0]["equipment"] = list(equipment)
    return d


def problems(d) -> list[str]:
    try:
        parse_recipe(d)
    except RecipeFormatError as exc:
        return exc.problems
    raise AssertionError("parsed")


def workshop():
    """The step-facts kitchen, with a Capability hierarchy: Heating, and under it Broiler heat (an oven
    or a grill) and Oven heat (an oven or a toaster oven)."""
    g = kitchen()
    g.add("TypeHierarchy", "Capability", "Capability")
    for tool in ("Grill", "Toaster oven"):
        g.add("DomainType", tool, tool, hierarchy=Ref("Equipment Type"))
    g.add("DomainType", "Heating", "Heating", hierarchy=Ref("Capability"), children=[Ref("Broiler heat"), Ref("Oven heat")],
          functionBorneBy=[])
    g.add("DomainType", "Broiler heat", "Broiler heat", hierarchy=Ref("Capability"), parent=Ref("Heating"), children=[],
          functionBorneBy=[Ref("Oven"), Ref("Grill")])
    g.add("DomainType", "Oven heat", "Oven heat", hierarchy=Ref("Capability"), parent=Ref("Heating"), children=[],
          functionBorneBy=[Ref("Toaster oven"), Ref("Oven")])
    return g


class Parse(unittest.TestCase):
    def test_a_capability_as_the_file_says_it(self):
        step = parse_recipe(data()).steps[0]
        self.assertEqual((step.equipment, step.capabilities, step.heat),
                         (("Saucepan", "Broiler heat"), ("Broiler heat",), (Heat("Broiler heat", level="high"),)))
        self.assertEqual(parse_recipe(data("Saucepan", {"tool": "Oven"})).steps[0].capabilities, ())

    def test_what_is_refused(self):
        cases = [
            ("a tool or a capability, one of them", data({"tool": "Oven", "capability": "Oven heat"})),
            ("a tool or a capability, one of them", data({"temp": 400, "unit": "F"})),
            ("listed twice", data({"capability": "Oven heat"}, {"capability": "Oven heat", "temp": 400, "unit": "F"})),
            ("heat must be one of", data({"capability": "Broiler heat", "heat": "scorching"})),
        ]
        for fragment, d in cases:
            self.assertTrue(any(fragment in p for p in problems(d)), (fragment, problems(d)))


class Load(unittest.TestCase):
    def test_written_as_an_instrument_that_specifies_the_capability_and_read_back(self):
        g, doc = workshop(), parse_recipe(data())
        report = import_recipe(g, doc)
        spec = g.nodes[[n["id"] for n in g.nodes.values() if n["type"] == "Specification" and n["name"].endswith("Broiler heat")][0]]
        self.assertEqual((spec["name"], spec["hasParticipationRole"], spec["specifies"].id),
                         ("Broiled Chicken v1 step 1 equipment 2 Broiler heat", "instrument", "Broiler heat"))
        self.assertEqual(export_plan(g, report.plan_id), doc.plan_part())
        self.assertTrue(import_recipe(g, doc).plan_unchanged)
        as_a_tool = parse_recipe(data("Saucepan", {"tool": "Oven", "temp": 450, "unit": "F"}))
        import_recipe(g, as_a_tool)
        self.assertEqual(export_plan(g, report.plan_id), as_a_tool.plan_part())

    def test_a_capability_is_one_and_a_tool_is_a_tool(self):
        cases = {
            "capability 'Oven' exists but is not in the right hierarchy": data({"capability": "Oven"}),
            "equipment 'Oven heat' exists but is not in the right hierarchy": data({"tool": "Oven heat"}),
            "capability 'Smoker heat' is not in the vocabulary": data({"capability": "Smoker heat"}),
        }
        for fragment, d in cases.items():
            with self.assertRaises(RecipeResolutionError) as caught:
                import_recipe(workshop(), parse_recipe(d))
            self.assertTrue(any(fragment in p for p in caught.exception.problems), (fragment, caught.exception.problems))

    def test_what_can_give_it_named_in_the_sentence(self):
        g, doc = workshop(), parse_recipe(data())
        self.assertEqual(capability_bearers(g, doc.steps), {"Broiler heat": ("Grill", "Oven")})
        self.assertEqual(instructions(doc.steps, capability_bearers(g, doc.steps)),
                         ["Roast 300 g chicken on the grill or oven over high heat using the saucepan."])
        heating = parse_recipe(data({"capability": "Heating"})).steps
        self.assertEqual(capability_bearers(g, heating), {"Heating": ("Grill", "Oven", "Toaster oven")})   # its subtypes' too


if __name__ == "__main__":
    unittest.main()
