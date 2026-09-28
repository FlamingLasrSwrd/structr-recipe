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
Pantry "Basic" inherits "Bare" (salt 13 oz, oil 24 fl oz), adds 6 eggs and restates salt as 500 g. In grams:
  oil  24 fl oz x 29.5735 mL x 0.92 g/mL (its density) = 652.983 g
  eggs 6 x 50 g (its weight per item) = 300 g
"""

import unittest
from datetime import datetime, timezone

from mealplanner.defaults import AmbiguousDefaultError, resolve_all
from mealplanner.inventory import current_magnitude
from mealplanner.profiles import (
    ProfileError, dietary_targets, import_profiles, instantiate_kitchen, instantiate_nutrition, instantiate_pantry,
    kitchen_items, pantry_stock, parse_profiles,
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
PANTRY = {"profile": [
    {"name": "Bare", "stock": [{"item": "Salt", "amount": 13, "unit": "oz"}, {"item": "Oil", "amount": 24, "unit": "fl_oz"}]},
    {"name": "Basic", "parent": "Bare", "stock": [{"item": "Egg", "amount": 6, "unit": "each"},
                                                  {"item": "Salt", "amount": 500, "unit": "g"}]},
]}
NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
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
    add_foods(g)
    import_profiles(g, parse_profiles(DIETARY, "dietary"), parse_profiles(KITCHEN, "kitchen"),
                    parse_profiles(PANTRY, "pantry"))
    return g


def add_foods(g):
    """Four foods: salt (a mass is enough), oil with a density, eggs with a weight per item, and milk
    with neither, so only a mass of milk converts to grams."""
    g.add("TypeHierarchy", "Food Identity", "Food Identity")
    for kind in ("Density", "MassPerUnit"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Default Kind"), defaultSpecifications=[])
    g.add("DomainType", "Mass", "Mass", defaultSpecifications=[])
    for food in ("Salt", "Oil", "Egg", "Milk"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), defaultSpecifications=[])
    for food, kind, value, unit in (("Oil", "Density", 0.92, "g_per_mL"), ("Egg", "MassPerUnit", 50.0, "g_per_each")):
        g.add("QuantitySpecification", f"{food} {kind} value", value=value, unit=unit, status="default")
        g.add("DefaultSpecification", f"{food} {kind}", forType=Ref(food), hasKind=Ref(kind), keyedBy=[],
              hasValue=Ref(f"{food} {kind} value"))
        g.nodes[food]["defaultSpecifications"].append(Ref(f"{food} {kind}"))


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

    def test_a_day_ends_at_the_owners_midnight(self):
        g = instance()
        instantiate_nutrition(g, {**self.SELECTION, "timezone": "America/Denver"})
        self.assertEqual(self.target(g, "Protein")[0]["dayBoundaryRule"], "midnight America/Denver")
        g2 = instance()
        instantiate_nutrition(g2, self.SELECTION)
        self.assertEqual(self.target(g2, "Protein")[0]["dayBoundaryRule"], "midnight")
        with self.assertRaises(ProfileError):
            instantiate_nutrition(instance(), {**self.SELECTION, "timezone": "Mountain Time"})

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


class PantryDefinitions(unittest.TestCase):
    def test_every_problem_is_reported(self):
        bad = {"profile": [{"name": "P", "stock": [
            {"item": "Salt", "amount": 0, "unit": "g"}, {"item": "Oil", "amount": 1, "unit": "glug"},
            {"item": "Egg", "amount": True, "unit": "each"}, {"item": "Salt", "amount": 5, "unit": "g"}]}]}
        with self.assertRaises(ProfileError) as caught:
            parse_profiles(bad, "pantry")
        self.assertEqual(len(caught.exception.problems), 4)

    def test_a_child_inherits_and_restates(self):
        stock = {name: (q["value"], q["unit"]) for name, q in pantry_stock(instance(), "Basic").values()}
        self.assertEqual(stock, {"Salt": (500.0, "g"), "Oil": (24.0, "fl_oz"), "Egg": (6.0, "each")})
        bare = {name for name, _ in pantry_stock(instance(), "Bare").values()}
        self.assertEqual(bare, {"Salt", "Oil"})

    def test_a_food_not_in_the_vocabulary_or_not_countable_in_grams_is_refused(self):
        g = WritableGraph()
        g.add("TypeHierarchy", "Default Kind", "Default Kind")
        add_foods(g)
        for stock, text in (([{"item": "Flour", "amount": 1, "unit": "lb"}], "not in the vocabulary"),
                            ([{"item": "Milk", "amount": 1, "unit": "cup"}], "no density"),
                            ([{"item": "Oil", "amount": 2, "unit": "each"}], "no weight per item")):
            with self.assertRaises(ProfileError) as caught:
                import_profiles(g, (), (), parse_profiles({"profile": [{"name": "P", "stock": stock}]}, "pantry"))
            self.assertIn(text, caught.exception.problems[0])


class Pantry(unittest.TestCase):
    SELECTION = {"name": "Home pantry", "profile": "Basic", "add": [{"item": "Milk", "amount": 1, "unit": "lb"}],
                 "remove": ["Egg"]}

    def lot(self, g, food):
        name = f"Home pantry -- {food}"
        return g.nodes[f"PortionOfSubstance:{name}"], g.nodes[f"Measurement:{name} mass assumed"]

    def test_the_owners_stock_is_an_assumption_derived_from_where_it_came_from(self):
        g = instance()
        instantiate_pantry(g, self.SELECTION, now=NOW)
        lots = sorted(n["name"] for n in g.nodes.values() if n["type"] == "PortionOfSubstance")
        self.assertEqual(lots, ["Home pantry -- Milk", "Home pantry -- Oil", "Home pantry -- Salt"])
        portion, m = self.lot(g, "Oil")
        self.assertEqual(portion["instanceOf"].id, "Oil")
        self.assertEqual((m["value"], m["unit"], m["status"], m["hasTime"]), (24.0, "fl_oz", "imputed", "2026-09-27T12:00:00+0000"))
        self.assertEqual(m["wasDerivedFrom"].id, "QuantitySpecification:Bare -- Oil amount")    # the profile's
        milk = self.lot(g, "Milk")[1]["wasDerivedFrom"].id
        self.assertEqual(milk, "QuantitySpecification:Home pantry -- Milk amount")              # the owner's own
        self.assertEqual(g.nodes[milk]["status"], "specified")
        self.assertEqual(self.lot(g, "Salt")[1]["wasDerivedFrom"].id, "QuantitySpecification:Basic -- Salt amount")

    def test_the_inventory_engine_counts_it_in_grams_from_when_it_was_written(self):
        g = instance()
        instantiate_pantry(g, {**self.SELECTION, "remove": []}, now=NOW)
        grams = {}
        for food in ("Salt", "Oil", "Egg", "Milk"):
            portion, _ = self.lot(g, food)
            grams[food] = current_magnitude(g, portion["bearerOf"][0].id, NOW)
        self.assertAlmostEqual(grams["Oil"], 652.983, places=2)
        self.assertEqual((grams["Salt"], grams["Egg"]), (500.0, 300.0))
        self.assertAlmostEqual(grams["Milk"], 453.592, places=3)
        before = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self.assertIsNone(current_magnitude(g, self.lot(g, "Salt")[0]["bearerOf"][0].id, before))

    def test_again_changes_nothing_and_an_edit_in_structr_is_kept_unless_reset(self):
        g = instance()
        instantiate_pantry(g, self.SELECTION, now=NOW)
        later = datetime(2026, 10, 1, tzinfo=timezone.utc)
        again = instantiate_pantry(g, self.SELECTION, now=later)
        self.assertEqual((again.counts["created"], again.counts["changed"]), (0, 0))
        self.assertEqual(self.lot(g, "Oil")[1]["hasTime"], "2026-09-27T12:00:00+0000")
        self.lot(g, "Oil")[1]["value"] = 10.0                         # the owner corrects it in Structr
        report = instantiate_pantry(g, self.SELECTION, now=later)
        self.assertEqual(report.kept, ["Home pantry -- Oil: 10 fl_oz (pantry profile 'Basic' says 24 fl_oz)"])
        self.assertEqual(self.lot(g, "Oil")[1]["value"], 10.0)
        instantiate_pantry(g, self.SELECTION, reset=True, now=later)
        self.assertEqual((self.lot(g, "Oil")[1]["value"], self.lot(g, "Oil")[1]["hasTime"]), (24.0, "2026-10-01T00:00:00+0000"))

    def test_a_new_source_rewrites_it_and_a_dropped_override_is_cleaned_up(self):
        g = instance()
        instantiate_pantry(g, self.SELECTION, now=NOW)
        later = datetime(2026, 10, 1, tzinfo=timezone.utc)
        instantiate_pantry(g, {**self.SELECTION, "add": [{"item": "Oil", "amount": 1, "unit": "l"}]}, now=later)
        oil = self.lot(g, "Oil")[1]
        self.assertEqual((oil["value"], oil["unit"], oil["hasTime"]), (1.0, "l", "2026-10-01T00:00:00+0000"))
        self.assertNotIn("PortionOfSubstance:Home pantry -- Milk", g.nodes)
        self.assertNotIn("QuantitySpecification:Home pantry -- Milk amount", g.nodes)
        instantiate_pantry(g, self.SELECTION, now=later)               # the oil override dropped: back to the profile
        self.assertEqual(self.lot(g, "Oil")[1]["wasDerivedFrom"].id, "QuantitySpecification:Bare -- Oil amount")
        self.assertNotIn("QuantitySpecification:Home pantry -- Oil amount", g.nodes)

    def test_a_removal_keeps_what_has_history(self):
        g = instance()
        instantiate_pantry(g, {**self.SELECTION, "remove": []}, now=NOW)
        g.add("Allocation", "a cook")
        g.nodes["PortionOfSubstance:Home pantry -- Salt"]["allocationsAbout"] = [Ref("a cook")]
        quality = self.lot(g, "Oil")[0]["bearerOf"][0].id
        g.add("Measurement", "a weighing", status="observed", value=400.0, unit="g")
        g.nodes[quality]["measurements"].append(Ref("a weighing"))
        report = instantiate_pantry(g, {**self.SELECTION, "remove": ["Salt", "Oil", "Egg"]}, now=NOW)
        self.assertEqual(sorted(report.refused), ["Home pantry -- Oil", "Home pantry -- Salt"])
        self.assertEqual(report.removed, ["Home pantry -- Egg"])
        self.assertNotIn("Quality:Home pantry -- Egg mass Quality", g.nodes)
        self.assertNotIn("Measurement:Home pantry -- Egg mass assumed", g.nodes)

    def test_a_pantry_named_like_a_profile_leaves_the_profile_alone(self):
        g = instance()
        instantiate_pantry(g, {"name": "Bare", "profile": "Basic"}, now=NOW)
        self.assertIn("QuantitySpecification:Bare -- Oil amount", g.nodes)
        self.assertEqual({n for n, _ in pantry_stock(g, "Bare").values()}, {"Salt", "Oil"})

    def test_what_cannot_be_instantiated_is_refused(self):
        for selection in ({"add": ["Flour"]}, {"add": ["Oil"]}, {"add": [{"item": "Milk", "amount": 1, "unit": "cup"}]},
                          {"remove": ["Flour"]}, {"name": "Home, pantry"}):
            with self.subTest(selection=selection), self.assertRaises(ProfileError):
                instantiate_pantry(instance(), {"profile": "Basic", **selection}, now=NOW)


if __name__ == "__main__":
    unittest.main()
