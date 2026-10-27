"""Cascading delete of what a recipe's Step owns (mealplanner/cascade_schema.py, scripts/44a): the
relationships, what the importer then deletes, and the check 44a makes before turning it on."""

import unittest
from collections import Counter

from mealplanner.cascade_schema import CASCADING, declarations, not_cascading, owned_by, shared_targets
from mealplanner.recipe_import import export_plan, import_recipe, parse_recipe
from tests.fakegraph import Ref, cascading_schema
from tests.test_recipe_step_facts import data, kitchen

ROAST = "Step:Roast Chicken and Rice v1 step 3 -- roast the chicken"        # the fake's ids are type:name


def without_roasting():
    """The fixture's recipe without its roasting step: the serving step takes the chicken as it is."""
    d = data()
    del d["steps"][2]
    d["steps"][2]["after"] = ["simmer the rice"]
    d["steps"][2]["inputs"][1] = {"food": "Chicken", "amount": 300, "unit": "g"}
    return parse_recipe(d)


class Relationships(unittest.TestCase):
    def test_the_seven_from_owner_to_owned(self):
        self.assertEqual([(s, r, t) for s, r, t, *_ in declarations()], [
            ("Step", "HAS_SPECIFICATION", "Specification"),
            ("Step", "HAS_WORKING_TIME", "QuantitySpecification"),
            ("Step", "HAS_WAITING_TIME", "QuantitySpecification"),
            ("Specification", "HAS_SPECIFIED_QUANTITY", "QuantitySpecification"),
            ("Specification", "HAS_STATE_REQUIREMENT", "StateRequirement"),
            ("Specification", "HAS_SUBSTITUTION_RULE", "SubstitutionRule"),
            ("StateRequirement", "EXPECTED_VALUE_QTY", "QuantitySpecification")])

    def test_each_named_by_the_property_on_its_owner(self):
        self.assertEqual(owned_by(), {"Step": ["hasSpecification", "hasWorkingTime", "hasWaitingTime"],
                                      "Specification": ["hasSpecifiedQuantity", "hasStateRequirement", "hasSubstitutionRule"],
                                      "StateRequirement": ["expectedValueQty"]})

    def test_an_instance_without_44a_lacks_all_seven(self):
        before, after = kitchen(), kitchen()
        for row in before.nodes.values():
            if row["type"] == "SchemaRelationshipNode":
                row["cascadingDeleteFlag"] = 0
        self.assertEqual(not_cascading(before), list(CASCADING))
        self.assertEqual(not_cascading(after), [])


class Importing(unittest.TestCase):
    def test_a_removed_step_takes_everything_it_owned(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        # By hand: Specifications for the chicken, the roasted chicken and the oven (3); quantities for the
        # chicken, 5 and 25 minutes, 425 and 165 F (5); requirements for the oven's heat, the doneness and the
        # temperature inside (3)
        owned = [g.nodes[n]["type"] for n in self.owned(g, ROAST)]
        self.assertEqual(Counter(owned), {"Specification": 3, "QuantitySpecification": 5, "StateRequirement": 3})
        before = set(g.nodes)
        deleted = []
        delete = g.delete
        g.delete = lambda path: (deleted.append(path), delete(path))
        edited = without_roasting()
        report = import_recipe(g, edited)
        self.assertEqual(export_plan(g, report.plan_id), edited.plan_part())
        # The serving step moves from 4 to 3, a new name, so the old one goes too, with its two inputs and
        # what it makes, the dish. The importer deletes the two Steps and nothing else; Structr (here the
        # fake) deletes the rest
        self.assertEqual([p.split("/")[3] for p in deleted], ["Step", "Step"])
        self.assertEqual(len(before - set(g.nodes)), 1 + 11 + 1 + 3)
        self.assertEqual(g.named("StateRequirement"), ["Roast Chicken and Rice v1 step 2 equipment 2 Stove heat"])
        self.assertEqual(g.named("QuantitySpecification", "roast"), [])
        self.assertEqual(g.named("Specification", "step 4"), [])

    def test_a_removed_ingredient_takes_its_quantity_and_rules(self):
        g = kitchen()
        g.add("DomainType", "Turkey", "Turkey", hierarchy=g.nodes["Chicken"]["hierarchy"], nutrientProfilesAbout=[],
              defaultSpecifications=[])
        d = data()
        d["steps"][0]["inputs"].append({"food": "Chicken", "amount": 50, "unit": "g", "substitutes": [{"food": "Turkey"}]})
        import_recipe(g, parse_recipe(d))
        self.assertEqual(len(g.named("SubstitutionRule")), 1)
        report = import_recipe(g, parse_recipe(data()))
        self.assertIn("Roast Chicken and Rice v1 step 1 input 2 Chicken", report.removed)
        self.assertEqual(g.named("SubstitutionRule"), [])
        self.assertEqual(g.named("QuantitySpecification", "step 1 input 2"), [])

    def test_before_44a_each_goes_by_hand(self):
        """A rebuild's scripts before 44a import too: there the importer deletes what Structr would."""
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        owned = self.owned(g, ROAST)
        cascading_schema(g, flag=0)
        deleted = []
        delete = g.delete
        g.delete = lambda path: (deleted.append(path), delete(path))
        edited = without_roasting()
        report = import_recipe(g, edited)
        self.assertEqual(export_plan(g, report.plan_id), edited.plan_part())
        self.assertFalse(any(n in g.nodes for n in owned))
        self.assertEqual(Counter(p.split("/")[3] for p in deleted),       # the 11 the roasting step owned, the
                         {"Specification": 6, "QuantitySpecification": 5,  # old serving step's 2 inputs and its
                          "StateRequirement": 3, "Step": 2})                 # output, and the two Steps
        self.assertEqual(g.named("StateRequirement"), ["Roast Chicken and Rice v1 step 2 equipment 2 Stove heat"])

    @staticmethod
    def owned(g, node_id):
        node = g.nodes[node_id]
        out = []
        for key in owned_by().get(node["type"], []):
            value = node.get(key)
            for ref in value if isinstance(value, list) else [value] if value else []:
                out.append(ref.id)
                out.extend(Importing.owned(g, ref.id))
        return out


class SharedTargets(unittest.TestCase):
    def test_none_after_an_import(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        self.assertEqual(shared_targets(g), [])

    def test_a_quantity_two_specifications_hold(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        chicken = "Specification:Roast Chicken and Rice v1 step 3 input 1 Chicken"
        output = "Specification:Roast Chicken and Rice v1 step 3 output Chicken (roasted)"
        g.patch(f"/structr/rest/Specification/{output}", {"hasSpecifiedQuantity": g.nodes[chicken]["hasSpecifiedQuantity"].id})
        self.assertEqual(shared_targets(g), [
            "QuantitySpecification Roast Chicken and Rice v1 step 3 input 1 Chicken quantity: held by 2 nodes"])

    def test_a_cook_fulfilling_a_specification_only_refers_to_it(self):
        """A cooked recipe's Specifications are fulfilled by its cook's Allocations (on the first rebuild,
        44a named nine such): a reference, not a second owner. A default's value is a holder."""
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        for name, rel, source, target, on_target in (("fulfills", "FULFILLS", "Allocation", "Specification", "allocations"),
                                                     ("value", "HAS_VALUE", "DefaultSpecification", "QuantitySpecification",
                                                      "defaultSpecification")):
            g.add("SchemaNode", f"schema:{source}", source, inheritedTraits=[])
            g.add("SchemaRelationshipNode", f"schema:{rel}", rel, relationshipType=rel, sourceId=f"schema:{source}",
                  targetId=f"schema:{target}", sourceJsonName=on_target, targetJsonName=name, cascadingDeleteFlag=0)
        chicken = "Specification:Roast Chicken and Rice v1 step 3 input 1 Chicken"
        g.add("Allocation", "a cook's allocation", fulfills=Ref(chicken))
        g.nodes[chicken]["allocations"] = [Ref("a cook's allocation")]
        self.assertEqual(shared_targets(g), [])
        quantity = g.nodes[chicken]["hasSpecifiedQuantity"].id
        g.add("DefaultSpecification", "a default", hasValue=Ref(quantity))
        g.nodes[quantity]["defaultSpecification"] = Ref("a default")
        self.assertEqual(shared_targets(g), [
            "QuantitySpecification Roast Chicken and Rice v1 step 3 input 1 Chicken quantity: held by 2 nodes"])

    def test_a_step_time_another_relationship_also_holds(self):
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        wait = g.nodes[ROAST]["hasWaitingTime"].id
        g.patch(f"/structr/rest/Step/{ROAST}", {"hasWorkingTime": wait})
        self.assertEqual(len(shared_targets(g)), 0)             # one Step holding it twice is one holder
        rinse = "Step:Roast Chicken and Rice v1 step 1 -- rinse the rice"
        g.patch(f"/structr/rest/Step/{rinse}", {"hasWaitingTime": wait})
        self.assertEqual([line.split(":")[-1] for line in shared_targets(g)], [" held by 2 nodes"])


class Fixture(unittest.TestCase):
    def test_the_fake_deletes_only_along_rows_with_the_flag(self):
        """Else the importer's tests above would pass whatever the fake did."""
        g = kitchen()
        import_recipe(g, parse_recipe(data()))
        owned = Importing.owned(g, ROAST)
        cascading_schema(g, flag=0)
        g.delete(f"/structr/rest/Step/{ROAST}")
        self.assertTrue(all(n in g.nodes for n in owned))
        rinse = "Step:Roast Chicken and Rice v1 step 1 -- rinse the rice"
        owned = Importing.owned(g, rinse)
        cascading_schema(g, flag=1)
        g.delete(f"/structr/rest/Step/{rinse}")
        self.assertTrue(owned and not any(n in g.nodes for n in owned))


if __name__ == "__main__":
    unittest.main()
