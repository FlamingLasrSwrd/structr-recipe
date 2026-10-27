"""A recipe step's facts (data-model.md J35; docs/recipe-format.md): working and waiting time, the
steps before it, a tool's heat and the doneness of what it makes. Parsed with every problem named,
written by the loader onto types the model already has, and read back as the file says them, so a
file loaded twice is unchanged and an edited one leaves nothing behind."""

import tomllib
import unittest

from mealplanner.recipe_import import (
    Heat, RecipeFormatError, RecipeResolutionError, export_plan, import_recipe, parse_recipe,
)
from tests.fakegraph import Ref, WritableGraph

FILE = """
name = "Roast Chicken and Rice"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "rinse the rice"
makes = "Rice (rinsed)"
minutes = 2
inputs = [{ food = "Rice", amount = 150, unit = "g" }]

[[steps]]
name = "simmer the rice"
method = "Simmering"
makes = "Rice (cooked)"
minutes = 2
wait_minutes = 18
equipment = ["Saucepan", { tool = "Stove", heat = "low" }]
inputs = [{ food = "Rice (rinsed)" }]

[[steps]]
name = "roast the chicken"
method = "Roasting"
makes = "Chicken (roasted)"
after = []
minutes = 5
wait_minutes = 25
until = "golden"
inside = { temp = 165, unit = "F" }
equipment = [{ tool = "Oven", temp = 425, unit = "F" }]
inputs = [{ food = "Chicken", amount = 300, unit = "g" }]

[[steps]]
name = "serve"
after = ["simmer the rice", "roast the chicken"]
inputs = [{ food = "Rice (cooked)" }, { food = "Chicken (roasted)" }]
"""


def data(**step_changes):
    d = tomllib.loads(FILE)
    for index, changes in step_changes.items():
        d["steps"][int(index[1:]) - 1].update(changes)
    return d


def problems(d) -> list[str]:
    with self_raises() as caught:
        parse_recipe(d)
    return caught.problems


class self_raises:
    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        if not isinstance(error, RecipeFormatError):
            raise AssertionError(f"expected RecipeFormatError, got {error!r}")
        self.problems = error.problems
        return True


class Parse(unittest.TestCase):
    def test_the_facts_as_the_file_says_them(self):
        rinse, simmer, roast, serve = parse_recipe(data()).steps
        self.assertEqual((rinse.minutes, rinse.wait_minutes, rinse.after), (2.0, None, None))
        self.assertEqual((simmer.minutes, simmer.wait_minutes, simmer.after), (2.0, 18.0, None))   # after the one before
        self.assertEqual(simmer.equipment, ("Saucepan", "Stove"))
        self.assertEqual(simmer.heat, (Heat("Stove", level="low"),))
        self.assertEqual((roast.after, roast.until, roast.inside), ((), "golden", (165.0, "F")))
        self.assertEqual(roast.heat, (Heat("Oven", temp=425.0, unit="F"),))
        self.assertEqual(serve.after, (2, 3))

    def test_naming_the_default_is_the_default(self):
        doc = parse_recipe(data(s2={"after": ["rinse the rice"]}, s1={"after": []}))
        self.assertEqual((doc.steps[0].after, doc.steps[1].after), (None, None))

    def test_what_is_refused(self):
        cases = {
            "heat must be one of": data(s2={"equipment": [{"tool": "Stove", "heat": "scorching"}]}),
            "a temperature or a heat level, not both": data(s2={"equipment": [{"tool": "Stove", "heat": "low", "temp": 300, "unit": "F"}]}),
            "a unit of F or C": data(s3={"equipment": [{"tool": "Oven", "temp": 425}]}),
            "a unit with no temperature": data(s3={"equipment": [{"tool": "Oven", "unit": "F"}]}),
            "unknown key 'power'": data(s3={"equipment": [{"tool": "Oven", "power": 9}]}),
            "until is a few words of doneness": data(s3={"until": "Roast until the skin is deep golden and crisp all over, about 25 minutes."}),
            "inside is a temperature the food reaches": data(s3={"inside": {"temp": 165}}),
            "minutes must be a number from 0": data(s1={"minutes": -2}),
            "wait_minutes must be a number from 0": data(s2={"wait_minutes": "a while"}),
            "after names 'cook the rice', which is no earlier step": data(s4={"after": ["cook the rice", "roast the chicken"]}),
            "after must be a list of the names of earlier steps": data(s4={"after": "simmer the rice"}),
        }
        for fragment, d in cases.items():
            self.assertTrue(any(fragment in p for p in problems(d)), (fragment, problems(d)))

    def test_a_step_using_what_another_makes_comes_after_it(self):
        found = problems(data(s4={"after": ["roast the chicken"]}))          # serve uses the rice, made in step 2
        self.assertTrue(any("step 4 uses 'Rice (cooked)', which step 2 makes, so it must come after it" in p for p in found), found)
        parse_recipe(data(s2={"after": ["rinse the rice"]}))                  # through the steps between is enough

    def test_two_steps_of_one_name_are_named_apart(self):
        d = data()
        d["steps"][2]["name"] = "simmer the rice"
        self.assertTrue(any("2 earlier steps: name them apart" in p for p in problems(d)))


class RecipeGraph(WritableGraph):
    """WritableGraph with what the loader writes: upsert, and every relation it sets."""

    RELATIONS = WritableGraph.RELATIONS | {"plan", "step", "specifies", "hasSpecifiedQuantity", "specializationOf",
                                           "hasRecipeYield", "hasMealType", "denotes", "hasWorkingTime", "hasWaitingTime",
                                           "isPrecededBy", "specification", "targetsProperty", "expectedValueQty",
                                           "forSpecification", "candidateType"}
    REVERSES = {**WritableGraph.REVERSES, "plan": "steps", "step": "hasSpecification", "specification": "hasStateRequirement",
                "hasWorkingTime": "workingTimeOfSteps", "hasWaitingTime": "waitingTimeOfSteps",
                "expectedValueQty": "expectedValueOfStateReqs", "hasSpecifiedQuantity": "specificationsWithThisQuantity",
                "forSpecification": "hasSubstitutionRule"}

    def upsert(self, type_name, unique_prop, value, fields, **_):
        found = [n for n in self.nodes.values() if n["type"] == type_name and n.get(unique_prop) == value]
        given = {k: v for k, v in fields.items() if v is not None}
        if found:
            self._store(found[0]["id"], given)
            return found[0]["id"]
        return self.post(f"/structr/rest/{type_name}", {unique_prop: value, **given})["result"][0]

    def named(self, type_name, fragment=""):
        return sorted(n["name"] for n in self.nodes.values() if n["type"] == type_name and fragment in n["name"])


def kitchen() -> RecipeGraph:
    g = RecipeGraph()
    for hid in ("Food Identity", "Transformation Method", "Equipment Type", "Quality Kind"):
        g.add("TypeHierarchy", hid, hid)
    for food in ("Rice", "Chicken"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), nutrientProfilesAbout=[], defaultSpecifications=[])
    for method in ("Simmering", "Roasting"):
        g.add("DomainType", method, method, hierarchy=Ref("Transformation Method"))
    for tool in ("Saucepan", "Stove", "Oven"):
        g.add("DomainType", tool, tool, hierarchy=Ref("Equipment Type"))
    for kind in ("Temperature", "Heat Level", "Doneness"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Quality Kind"))
    g.add("ConceptScheme", "Meal Type", "Meal Type")
    g.add("Concept", "Dinner", "Dinner", inScheme=Ref("Meal Type"))
    return g


class Load(unittest.TestCase):
    def test_loaded_and_read_back_as_the_file_says_it(self):
        g, doc = kitchen(), parse_recipe(data())
        report = import_recipe(g, doc)
        self.assertEqual(export_plan(g, report.plan_id), doc.plan_part())
        self.assertTrue(import_recipe(g, doc).plan_unchanged)
        roast = g.nodes[[n["id"] for n in g.nodes.values() if n["type"] == "Step" and "roast the chicken" in n["name"]][0]]
        self.assertEqual(g.nodes[roast["hasWaitingTime"].id]["value"], 25.0)
        self.assertEqual(g.nodes[roast["hasWaitingTime"].id]["unit"], "minutes")
        self.assertEqual(roast["isPrecededBy"], [])                            # side by side with the rice
        oven = g.nodes["StateRequirement:Roast Chicken and Rice v1 step 3 equipment 1 Oven heat"]
        self.assertEqual((oven["targetsProperty"].id, g.nodes[oven["expectedValueQty"].id]["unit"]), ("Temperature", "degF"))

    def test_an_edited_file_leaves_nothing_behind(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        edited_data = data(s2={"equipment": ["Saucepan", "Stove"]})
        del edited_data["steps"][1]["wait_minutes"]
        for key in ("until", "inside", "after"):
            del edited_data["steps"][2][key]
        edited = parse_recipe(edited_data)
        report = import_recipe(g, edited)
        self.assertFalse(report.plan_unchanged)
        self.assertEqual(export_plan(g, report.plan_id), edited.plan_part())
        self.assertEqual(g.named("StateRequirement"), ["Roast Chicken and Rice v1 step 3 equipment 1 Oven heat"])
        self.assertEqual(g.named("QuantitySpecification", "waiting time"), ["Roast Chicken and Rice v1 step 3 -- roast the chicken waiting time"])
        self.assertEqual(g.named("QuantitySpecification", "inside"), [])

    def test_what_an_output_requires_goes_with_it(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        renamed = data(s3={"makes": "Chicken (baked)"})
        renamed["steps"][3]["inputs"][1]["food"] = "Chicken (baked)"
        report = import_recipe(g, parse_recipe(renamed))
        self.assertIn("Roast Chicken and Rice v1 step 3 output Chicken (roasted)", report.removed)
        self.assertEqual(g.named("StateRequirement", "Chicken (roasted)"), [])
        self.assertEqual(g.named("QuantitySpecification", "Chicken (roasted)"), [])
        self.assertEqual(g.named("StateRequirement", "Chicken (baked)"),
                         ["Roast Chicken and Rice v1 step 3 output Chicken (baked) doneness",
                          "Roast Chicken and Rice v1 step 3 output Chicken (baked) inside"])

    def test_a_kind_not_loaded_is_named_before_anything_is_written(self):
        g = kitchen()
        del g.nodes["Doneness"]
        before = dict(g.nodes)
        with self.assertRaises(RecipeResolutionError) as caught:
            import_recipe(g, parse_recipe(data()))
        self.assertTrue(any("quality kind 'Doneness'" in p and "scripts/41a" in p for p in caught.exception.problems))
        self.assertEqual(g.nodes, before)


if __name__ == "__main__":
    unittest.main()
