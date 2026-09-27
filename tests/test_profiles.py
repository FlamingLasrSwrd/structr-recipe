"""Profiles (mealplanner/profiles.py): definitions, resolution up the hierarchy, and instantiation.

Worked out by hand for "Man moderately active" (energy 2,400-2,600 kcal, so 2,500 in the middle):
  Protein     floors 56 g (RDA) and 10% x 2500 / 4 = 62.5 g -> 62.5; ceiling 35% x 2500 / 4 = 218.75
  Carbohydrate floors 130 g and 45% x 2500 / 4 = 281.25 -> 281.25; ceiling 65% x 2500 / 4 = 406.25
  Total fat   20% x 2500 / 9 = 55.556 to 35% x 2500 / 9 = 97.222
  Fiber       14 g per 1000 kcal x 2.5 = 35 g, a floor
  Sodium      at most 2300 mg (from "Adult"); "Man low sodium" restates it: at most 1500 mg
  Vitamin C   at least 90 mg (from "Man")
Kitchen "Enthusiast" inherits "Minimal" (nonstick skillet 1, chef's knife 1, mixing bowl 2), adds a wok
and restates the bowls as 3.
"""

import unittest

from mealplanner.defaults import AmbiguousDefaultError, resolve_all
from mealplanner.profiles import (
    ProfileError, dietary_targets, import_profiles, instantiate_kitchen, instantiate_nutrition, kitchen_items,
    parse_profiles,
)
from tests.fakegraph import Ref, WritableGraph

S = "sourced"
DIETARY = {"profile": [
    {"name": "Adult", "intakes": [
        {"nutrient": 1093, "max": 2300, "unit": "mg", "source": "CDRR"},
        {"nutrient": 1003, "basis": "share of energy", "min": 10, "max": 35, "source": "AMDR"},
        {"nutrient": 1005, "min": 130, "unit": "g", "source": "RDA"},
        {"nutrient": 1005, "basis": "share of energy", "min": 45, "max": 65, "source": "AMDR"},
        {"nutrient": 1079, "basis": "per 1000 kcal", "min": 14, "unit": "g", "source": "DGA"},
        {"nutrient": 1004, "basis": "share of energy", "min": 20, "max": 35, "source": "AMDR"}]},
    {"name": "Man", "parent": "Adult", "intakes": [
        {"nutrient": 1003, "min": 56, "unit": "g", "source": "RDA"},
        {"nutrient": 1162, "min": 90, "unit": "mg", "source": "RDA"}]},
    {"name": "Man moderately active", "parent": "Man", "intakes": [
        {"nutrient": 1008, "min": 2400, "max": 2600, "unit": "kcal", "status": "calculated", "source": "EER bands"}]},
    {"name": "Man low sodium", "parent": "Man moderately active", "intakes": [
        {"nutrient": 1093, "max": 1500, "unit": "mg", "source": "a lower limit"}]},
    {"name": "Man impossible", "parent": "Man moderately active", "intakes": [
        {"nutrient": 1003, "min": 300, "unit": "g", "source": "above the 35% ceiling"}]},
]}
KITCHEN = {"profile": [
    {"name": "Minimal", "equipment": [{"item": "Nonstick skillet"}, {"item": "Chef's knife"},
                                      {"item": "Mixing bowl", "count": 2}]},
    {"name": "Enthusiast", "parent": "Minimal", "equipment": [{"item": "Wok"}, {"item": "Mixing bowl", "count": 3}]},
]}
NUTRIENTS = {"1008": ("Energy", "KCAL"), "1003": ("Protein", "G"), "1005": ("Carbohydrate", "G"),
             "1004": ("Total fat", "G"), "1093": ("Sodium - Na", "MG"), "1079": ("Fiber", "G"),
             "1162": ("Vitamin C", "MG")}


def instance():
    g = WritableGraph()
    for h in ("Default Kind", "Nutrient", "Equipment Type"):
        g.add("TypeHierarchy", h, h)
    g.add("Concept", "FDC nutrient id", "FDC nutrient id")
    for fdc, (name, _) in NUTRIENTS.items():
        g.add("DomainType", name, name, hierarchy=Ref("Nutrient"), defaultSpecifications=[])
        g.add("Identifier", f"{name} FDC nutrient id", identifierValue=fdc, identifierScheme=Ref("FDC nutrient id"),
              denotesType=Ref(name))
    for tool in ("Nonstick skillet", "Chef's knife", "Mixing bowl", "Wok"):
        g.add("DomainType", tool, tool, hierarchy=Ref("Equipment Type"), defaultSpecifications=[])
    import_profiles(g, parse_profiles(DIETARY, "dietary"), parse_profiles(KITCHEN, "kitchen"))
    return g


def by_name(targets):
    return {t.nutrient: t for t in targets}


class Parse(unittest.TestCase):
    def test_every_problem_is_reported(self):
        bad = {"profile": [
            {"name": "Child", "parent": "Nobody", "intakes": [
                {"nutrient": 1093, "min": 5, "max": 1, "unit": "mg", "source": "x"},
                {"nutrient": 1162, "basis": "share of energy", "min": 1, "source": "x"},
                {"nutrient": 1003, "min": 1, "unit": "cups", "source": "x"},
                {"nutrient": 1004, "min": 1, "unit": "g"},
                {"nutrient": 1005, "unit": "g", "source": "x"}]}]}
        with self.assertRaises(ProfileError) as caught:
            parse_profiles(bad, "dietary")
        for fragment in ("parent 'Nobody'", "min 5 is above max 1", "no kcal-per-gram factor", "'cups'",
                         "names its source", "give min, max or both"):
            self.assertTrue(any(fragment in p for p in caught.exception.problems), fragment)

    def test_a_kitchen_item_listed_twice(self):
        with self.assertRaises(ProfileError):
            parse_profiles({"profile": [{"name": "K", "equipment": [{"item": "Wok"}, {"item": "Wok"}]}]}, "kitchen")


class Resolve(unittest.TestCase):
    def test_a_child_inherits_and_converts_shares_of_energy(self):
        t = by_name(dietary_targets(instance(), "Man moderately active"))
        self.assertEqual((t["Protein"].minimum, t["Protein"].maximum, t["Protein"].unit), (62.5, 218.75, "g"))
        self.assertEqual((t["Carbohydrate"].minimum, t["Carbohydrate"].maximum), (281.25, 406.25))
        self.assertEqual((t["Total fat"].minimum, t["Total fat"].maximum), (55.556, 97.222))
        self.assertEqual((t["Fiber"].minimum, t["Fiber"].maximum), (35.0, None))
        self.assertEqual((t["Sodium - Na"].minimum, t["Sodium - Na"].maximum, t["Sodium - Na"].unit), (None, 2300, "mg"))
        self.assertEqual((t["Vitamin C"].minimum, t["Energy"].minimum, t["Energy"].maximum), (90, 2400, 2600))

    def test_statuses(self):
        t = by_name(dietary_targets(instance(), "Man moderately active"))
        self.assertEqual((t["Sodium - Na"].status, t["Protein"].status, t["Energy"].status), (S, "calculated", "calculated"))

    def test_a_restated_intake_overrides_the_ancestors(self):
        self.assertEqual(by_name(dietary_targets(instance(), "Man low sodium"))["Sodium - Na"].maximum, 1500)

    def test_goals_that_cannot_both_be_met_are_refused(self):
        with self.assertRaises(ProfileError) as caught:
            dietary_targets(instance(), "Man impossible")
        self.assertIn("'Protein' conflict (300 > 218.75)", caught.exception.problems[0])

    def test_a_default_of_another_kind_is_not_an_item(self):
        g = instance()
        g.add("QuantitySpecification", "q", value=1.0, unit="each")
        g.add("DefaultSpecification", "other", forType=Ref("DomainType:Minimal"), hasKind=Ref("Default Kind"),
              hasValue=Ref("q"), keyedBy=[Ref("Wok")])
        g.nodes["DomainType:Minimal"]["defaultSpecifications"].append(Ref("other"))
        self.assertNotIn("Wok", [name for name, _ in kitchen_items(g, "Minimal").values()])

    def test_a_kitchen_inherits_adds_and_restates(self):
        items = sorted(kitchen_items(instance(), "Enthusiast").values())
        self.assertEqual(items, [("Chef's knife", 1), ("Mixing bowl", 3), ("Nonstick skillet", 1), ("Wok", 1)])

    def test_two_defaults_with_one_signature_on_one_type_are_ambiguous(self):
        g = instance()
        g.add("QuantitySpecification", "q", value=1.0, unit="each")
        g.add("DefaultSpecification", "again", forType=Ref("DomainType:Minimal"), hasKind=Ref("DomainType:Kitchen Equipment"),
              hasValue=Ref("q"), keyedBy=[Ref("Wok")])
        g.nodes["DomainType:Minimal"]["defaultSpecifications"].append(Ref("again"))
        g.add("DefaultSpecification", "again 2", forType=Ref("DomainType:Minimal"), hasKind=Ref("DomainType:Kitchen Equipment"),
              hasValue=Ref("q"), keyedBy=[Ref("Wok")])
        g.nodes["DomainType:Minimal"]["defaultSpecifications"].append(Ref("again 2"))
        with self.assertRaises(AmbiguousDefaultError):
            resolve_all(g, "DomainType:Minimal", "DomainType:Kitchen Equipment")


class Nutrition(unittest.TestCase):
    SELECTION = {"profile": "Man moderately active", "weight": 0.1, "hard": ["Protein"], "leave_out": ["Fiber"],
                 "overrides": {"Sodium - Na": {"max": 2000, "unit": "mg"}}}

    def target(self, g, nutrient):
        row = g.nodes[f"NutritionTarget:Daily {nutrient} target"]
        rng = g.nodes[row["hasTargetRange"].id]
        return row, rng

    def test_the_owners_targets(self):
        g = instance()
        instantiate_nutrition(g, self.SELECTION)
        protein, prange = self.target(g, "Protein")
        self.assertEqual((protein["strictness"], protein.get("weight"), prange["minValue"], prange["status"]),
                         ("hard", None, 62.5, "default"))
        self.assertEqual((protein["hasTimeScope"], protein["dayBoundaryRule"]), ("daily", "midnight"))
        sodium, srange = self.target(g, "Sodium - Na")
        self.assertEqual((sodium["strictness"], sodium["weight"], srange["maxValue"], srange["status"]),
                         ("soft", 0.1, 2000, "specified"))
        self.assertIn("set by the owner", sodium["source"])
        self.assertNotIn("NutritionTarget:Daily Fiber target", g.nodes)
        self.assertIn("dietary profile 'Man moderately active'", self.target(g, "Vitamin C")[0]["source"])

    def test_again_changes_nothing(self):
        g = instance()
        instantiate_nutrition(g, self.SELECTION)
        report = instantiate_nutrition(g, self.SELECTION)
        self.assertEqual((report.counts["created"], report.counts["changed"]), (0, 0))

    def test_an_owners_edit_is_kept_unless_reset(self):
        g = instance()
        instantiate_nutrition(g, self.SELECTION)
        _, rng = self.target(g, "Vitamin C")
        rng["minValue"] = 120                                  # changed in Structr by the owner
        report = instantiate_nutrition(g, self.SELECTION)
        self.assertEqual((rng["minValue"], len(report.kept)), (120, 1))
        instantiate_nutrition(g, self.SELECTION, reset=True)
        self.assertEqual(rng["minValue"], 90)

    def test_a_dropped_override_goes_back_to_the_profile(self):
        g = instance()
        instantiate_nutrition(g, self.SELECTION)
        instantiate_nutrition(g, {**self.SELECTION, "overrides": {}})
        sodium, srange = self.target(g, "Sodium - Na")
        self.assertEqual((srange["maxValue"], srange["status"]), (2300, "default"))
        self.assertIn("dietary profile", sodium["source"])

    def test_a_target_left_out_later_is_deleted_unless_a_plan_uses_it(self):
        g = instance()
        instantiate_nutrition(g, self.SELECTION)
        g.add("MealPlan", "a week")
        g.nodes["NutritionTarget:Daily Vitamin C target"]["constrainedPlans"] = [Ref("a week")]
        report = instantiate_nutrition(g, {**self.SELECTION, "leave_out": ["Fiber", "Energy", "Vitamin C"]})
        self.assertEqual((report.removed, report.refused), (["Daily Energy target"], ["Daily Vitamin C target"]))
        self.assertNotIn("NutritionTarget:Daily Energy target", g.nodes)
        self.assertNotIn("QuantitySpecification:Daily Energy target range", g.nodes)
        self.assertIn("NutritionTarget:Daily Vitamin C target", g.nodes)

    def test_a_name_the_profile_lacks_is_refused(self):
        with self.assertRaises(ProfileError):
            instantiate_nutrition(instance(), {**self.SELECTION, "hard": ["Protien"]})


class Kitchen(unittest.TestCase):
    SELECTION = {"name": "Home", "profile": "Enthusiast", "add": [{"item": "Chef's knife", "count": 2}],
                 "remove": ["Wok"]}

    def members(self, g):
        return sorted(g.nodes[r.id]["name"] for r in g.nodes["UtensilSet:Home"].get("hasMemberPart", []))

    def test_the_owners_kitchen(self):
        g = instance()
        instantiate_kitchen(g, self.SELECTION)
        self.assertEqual(self.members(g), ["Home -- Chef's knife 1", "Home -- Chef's knife 2", "Home -- Mixing bowl 1",
                                           "Home -- Mixing bowl 2", "Home -- Mixing bowl 3", "Home -- Nonstick skillet 1"])
        knife = g.nodes["EquipmentObject:Home -- Chef's knife 2"]
        self.assertEqual(knife["instanceOf"].id, "Chef's knife")
        self.assertIn("added by the owner", knife["source"])
        self.assertIn("kitchen profile 'Enthusiast'", g.nodes["EquipmentObject:Home -- Mixing bowl 1"]["source"])

    def test_again_changes_nothing_and_a_removal_keeps_what_has_history(self):
        g = instance()
        instantiate_kitchen(g, self.SELECTION)
        self.assertEqual(instantiate_kitchen(g, self.SELECTION).counts["created"], 0)
        g.add("Allocation", "a cook")
        g.nodes["EquipmentObject:Home -- Mixing bowl 3"]["allocationsAbout"] = [Ref("a cook")]
        report = instantiate_kitchen(g, {**self.SELECTION, "remove": ["Wok", "Mixing bowl"]})
        self.assertEqual(sorted(report.removed), ["Home -- Mixing bowl 1", "Home -- Mixing bowl 2"])
        self.assertEqual(report.refused, ["Home -- Mixing bowl 3"])

    def test_an_unknown_item_is_refused(self):
        with self.assertRaises(ProfileError):
            instantiate_kitchen(instance(), {**self.SELECTION, "add": ["Spork"]})


if __name__ == "__main__":
    unittest.main()
