"""USDA FoodKeeper shelf lives (mealplanner/foodkeeper.py; data-model.md J31): the file read and
pinned, its ranges turned into days, loaded as ShelfLife defaults on foods (vocabulary_import.py),
and read back as a portion's expiry before its perishability class's (inventory.py).
"""

import json
import os
import tempfile
import unittest

from mealplanner.foodkeeper import figure, pin, read_products, shelf_lives
from mealplanner.inventory import assumed_storage, instance_expiration
from mealplanner.pantry import buy
from mealplanner.vocabulary_import import VocabularyError, import_vocabulary, parse_vocabulary
from tests.fakegraph import Ref, at, when
from tests.planning_graph import add_portion, add_type
from tests.test_pantry import NOW, pantry, portion_named
from tests.test_vocabulary import fdc_subset, instance, vocabulary_data

CHICKEN = {"ID": 117, "Name": "Chicken parts", "Name_subtitle": "breast halves, boneless",
           "DOP_Refrigerate_Min": 1.0, "DOP_Refrigerate_Max": 2.0, "DOP_Refrigerate_Metric": "Days",
           "DOP_Freeze_Min": 9.0, "DOP_Freeze_Max": 9.0, "DOP_Freeze_Metric": "Months"}
FLOUR = {"ID": 222, "Name": "Flour", "Name_subtitle": "white",
         "DOP_Pantry_Min": 6.0, "DOP_Pantry_Max": 12.0, "DOP_Pantry_Metric": "Months",
         "Pantry_After_Opening_Min": 6.0, "Pantry_After_Opening_Max": 8.0, "Pantry_After_Opening_Metric": "Months",
         "Refrigerate_After_Opening_Min": 1.0, "Refrigerate_After_Opening_Max": 1.0, "Refrigerate_After_Opening_Metric": "Year"}
MILK = {"ID": 27, "Name": "Milk", "Refrigerate_Metric": "Package use-by date", "Freeze_Metric": "Not Recommended"}
SALT = {"ID": 468, "Name": "Salt", "Pantry_Metric": "Indefinitely"}


def workbook(*products):
    cells = lambda row: [{k: v} for k, v in row.items()]
    return {"fileName": "FMA-Data-v128.xlsx", "sheets": [
        {"name": "Version", "data": [cells({"Data_Version_Number": 128.0, "Current_Version": "Yes", "Modified_Date": "09-06-2018"})]},
        {"name": "Category", "data": [cells({"ID": 15, "Category_Name": "Poultry", "Subcategory_Name": "Fresh"})]},
        {"name": "Product", "data": [cells({"Category_ID": 15, "Keywords": "x", "Refrigerate_tips": "tip", **p}) for p in products]},
    ]}


class Figures(unittest.TestCase):
    def test_the_least_of_a_range_in_days(self):
        self.assertEqual(figure(CHICKEN, "DOP_Refrigerate"), (1.0, "1-2 days"))
        self.assertEqual(figure(CHICKEN, "DOP_Freeze"), (270.0, "9 months"))
        self.assertEqual(figure(FLOUR, "Refrigerate_After_Opening"), (365.0, "1 year"))
        self.assertEqual(figure(SALT, "Pantry")[0], 3650.0)

    def test_no_number_is_no_figure(self):
        for column in ("Refrigerate", "Freeze", "Pantry"):
            self.assertIsNone(figure(MILK, column))

    def test_one_figure_holds_opened_or_not_and_two_are_keyed_apart(self):
        lives = {keys: days for keys, days, _ in shelf_lives(CHICKEN)}
        self.assertEqual(lives, {("Fridge",): 1.0, ("Freezer",): 270.0})
        lives = {keys: days for keys, days, _ in shelf_lives(FLOUR)}
        self.assertEqual(lives, {("Pantry", "Sealed"): 180.0, ("Pantry", "Opened"): 180.0, ("Fridge", "Opened"): 365.0})
        self.assertEqual(shelf_lives(MILK), [])
        (_, _, source), _ = shelf_lives(CHICKEN)
        self.assertIn("product 117 Chicken parts (breast halves, boneless): 1-2 days in the refrigerator from purchase", source)


class Pinned(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w") as fh:
            json.dump(workbook(CHICKEN, FLOUR, MILK), fh)
        self.addCleanup(os.remove, self.path)

    def test_the_products_asked_for_without_their_tips(self):
        products, version = read_products(self.path)
        self.assertEqual((sorted(products), version), ([27, 117, 222], {"version": 128.0, "modified": "09-06-2018"}))
        pinned = pin(self.path, {117})
        self.assertEqual(list(pinned["products"]), ["117"])
        chicken = pinned["products"]["117"]
        self.assertEqual((chicken["Category"], chicken["DOP_Refrigerate_Min"]), ("Poultry / Fresh", 1.0))
        self.assertNotIn("Refrigerate_tips", chicken)
        self.assertEqual(len(pinned["sha256"]), 64)
        with self.assertRaises(KeyError):
            pin(self.path, {999})


def table():
    return {"products": {"117": CHICKEN, "222": FLOUR, "27": MILK}}


def with_keeps(**foods):
    data = vocabulary_data()
    for food in data["food"]:
        if food["name"] in foods:
            food["foodkeeper"] = foods[food["name"]]
    return data


def shelf_instance():
    g = instance()
    for name in ("Fridge", "Freezer", "Pantry", "Sealed", "Opened", "ShelfLife"):
        g.add("DomainType", name, name)
    return g


class Loaded(unittest.TestCase):
    def node(self, g, type_name, name):
        (row,) = [r for r in g.get_all(type_name)["result"] if r["name"] == name]
        return row

    def load(self, g, data):
        return import_vocabulary(g, parse_vocabulary(data, fdc_subset(), shelf_table=table()))

    def test_shelf_lives_on_the_food_keyed_by_storage(self):
        g = shelf_instance()
        self.load(g, vocabulary_data())
        imported = self.load(g, with_keeps(Garlic=117, Onion={"id": 222, "proxy": True}))
        self.assertEqual(imported.affected, set())            # how long a food keeps changes no recipe's nutrition
        fridge = self.node(g, "DefaultSpecification", "Garlic shelf life Fridge")
        self.assertEqual((fridge["forType"]["name"], [k["name"] for k in fridge["keyedBy"]], fridge["provenance"]),
                         ("Garlic", ["Fridge"], "sourced"))
        self.assertEqual(self.node(g, "QuantitySpecification", "Garlic shelf life Fridge value")["value"], 1.0)
        opened = self.node(g, "DefaultSpecification", "Onion shelf life Pantry Opened")
        self.assertEqual(sorted(k["name"] for k in opened["keyedBy"]), ["Opened", "Pantry"])
        self.assertEqual(opened["provenance"], "estimated")
        self.assertIn("a near kind of food", opened["source"])
        again = self.load(g, with_keeps(Garlic=117, Onion={"id": 222, "proxy": True}))
        self.assertEqual((again.counts["created"], again.counts["changed"], again.counts["deleted"]), (0, 0, 0))

    def test_a_product_changed_leaves_no_stale_shelf_life(self):
        g = shelf_instance()
        self.load(g, with_keeps(Garlic=222))
        self.load(g, with_keeps(Garlic=117))
        names = sorted(r["name"] for r in g.get_all("DefaultSpecification")["result"] if " shelf life " in r["name"])
        self.assertEqual(names, ["Garlic shelf life Freezer", "Garlic shelf life Fridge"])
        self.assertFalse([r for r in g.get_all("QuantitySpecification")["result"] if "shelf life Pantry" in r["name"]])

    def test_what_cannot_be_named(self):
        for bad in (999, "117", {"id": 117, "kind": "x"}):
            with self.assertRaises(VocabularyError):
                parse_vocabulary(with_keeps(Garlic=bad), fdc_subset(), shelf_table=table())


def keeps(g, food, days, *keys):
    name = f"{food} shelf life {' '.join(keys)}"
    g.add("QuantitySpecification", f"{name} value", value=days, unit="days")
    g.add("DefaultSpecification", name, hasKind=Ref("ShelfLife"), keyedBy=[Ref(k) for k in keys], hasValue=Ref(f"{name} value"))
    g.nodes[food]["defaultSpecifications"].append(Ref(name))


class Expiry(unittest.TestCase):
    def test_the_foods_own_shelf_life_comes_before_its_class(self):
        g = pantry()
        keeps(g, "Eggs", 21.0, "Fridge")                       # FoodKeeper's 3 weeks, against Fresh Meat's 5 days
        buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        eggs = g.get_all("PortionOfSubstance", portion_named(g, "Purchase t1 -- Eggs"))["result"]
        self.assertEqual(instance_expiration(g, eggs, when(26, 12)), (False, 20.0))

    def test_a_portion_in_no_container_is_kept_where_its_food_keeps(self):
        g = pantry()
        add_type(g, "Flour")
        keeps(g, "Flour", 180.0, "Pantry", "Sealed")
        add_portion(g, "flour on hand", "Flour", 1000.0, at(25, 0))
        flour = g.get_all("PortionOfSubstance", "flour on hand")["result"]
        self.assertEqual(assumed_storage(g, flour), "Pantry")
        self.assertEqual(instance_expiration(g, flour, when(26, 0)), (False, 179.0))
        keeps(g, "Eggs", 21.0, "Fridge")
        add_portion(g, "eggs on hand", "Eggs", 300.0, at(25, 0))
        self.assertEqual(assumed_storage(g, g.get_all("PortionOfSubstance", "eggs on hand")["result"]), "Fridge")

    def test_a_purchase_says_nothing_of_a_class_when_the_food_keeps(self):
        g = pantry()
        keeps(g, "Eggs", 21.0, "Fridge")
        self.assertEqual(buy(g, "Eggs", 600, "g", NOW, "t1").notes, [])
        self.assertTrue(buy(g, "Noodles", 500, "g", NOW, "t2").notes)


if __name__ == "__main__":
    unittest.main()
