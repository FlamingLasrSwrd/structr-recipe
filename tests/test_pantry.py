"""Pantry bookings (mealplanner/pantry.py), read back through the inventory engine (inventory.py).

The kitchen is tests/test_planning_extract.py's: an omelette (yield 2) takes 300 g of eggs; pasta
(yield 2) takes 200 g of noodles and 100 g of eggs. Eggs are Fresh Meat here, for a shelf life:
5 days sealed in the fridge, 2 opened, 180 sealed in the freezer.
"""

import unittest

from mealplanner.inventory import instance_expiration
from mealplanner.pantry import PantryError, buy, cook, discard, move, on_hand, open_portion, stock_take, use
from tests.fakegraph import Ref, WritableGraph, at, when
from tests.planning_graph import add_entry, add_portion, add_type
from tests.test_planning_extract import kitchen

NOW = when(25, 12)


class Graph(WritableGraph):
    """The write side, with the relationships the pantry writes kept in both directions."""
    RELATIONS = WritableGraph.RELATIONS | {
        "process", "hasActualQuantity", "occupiesTemporalRegion", "beginsToExistDuring", "locatedIn",
        "hasStorageCondition", "hasOpenedStatus", "hasPerishabilityType", "concretizes", "fulfills", "fulfilledBy",
        "isAbout"}
    REVERSES = {**WritableGraph.REVERSES, "isAbout": "allocationsAbout", "process": "qualifiedUsage"}


def pantry():
    g = Graph()
    g.nodes = kitchen().nodes
    for name in ("Sealed", "Opened", "Fridge", "Freezer", "Pantry", "ShelfLife", "Fresh Meat", "Density", "MassPerUnit"):
        add_type(g, name)
    for keys, days in ((("Fridge", "Sealed"), 5.0), (("Fridge", "Opened"), 2.0), (("Freezer", "Sealed"), 180.0)):
        name = f"shelf {'+'.join(keys)}"
        g.add("QuantitySpecification", f"{name} value", value=days, unit="days")
        g.add("DefaultSpecification", name, hasKind=Ref("ShelfLife"), keyedBy=[Ref(k) for k in keys],
              hasValue=Ref(f"{name} value"))
        g.nodes["Fresh Meat"]["defaultSpecifications"].append(Ref(name))
    return g


def portion_named(g, name):
    (row,) = [n for n in g.nodes.values() if n["type"] == "PortionOfSubstance" and n["name"] == name]
    return row["id"]


def grams(g, portion_id, at_time):
    return on_hand(g, g.get_all("PortionOfSubstance", portion_id)["result"], at_time)


class Buy(unittest.TestCase):
    def test_a_purchase_is_stock_from_when_it_was_bought(self):
        g = pantry()
        booking = buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        self.assertEqual(booking.process, "Purchase t1")
        self.assertEqual((grams(g, eggs, NOW), grams(g, eggs, when(25, 11))), (600.0, None))
        expired, days = instance_expiration(g, g.get_all("PortionOfSubstance", eggs)["result"], when(27, 12))
        self.assertEqual((expired, days), (False, 3.0))                       # 5 days in the fridge, sealed
        process = g.get_all("Process", g.get_all("PortionOfSubstance", eggs)["result"]["beginsToExistDuring"]["id"])["result"]
        self.assertEqual(process["hasKind"]["name"], "Purchase")

    def test_the_same_booking_twice_writes_nothing_new(self):
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1")
        posts = g.posts
        self.assertEqual(buy(g, "Eggs", 600, "g", NOW, "t1").created, [])
        self.assertEqual(g.posts, posts)

    def test_one_trip_is_one_purchase(self):
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1")
        buy(g, "Noodles", 500, "g", NOW, "t1")
        self.assertEqual(len([n for n in g.nodes.values() if n["type"] == "Process"]), 1)

    def test_a_class_is_taken_from_the_last_portion_of_the_food_that_has_one(self):
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        self.assertEqual(buy(g, "Eggs", 300, "g", NOW, "t2").notes, [])
        self.assertEqual(g.nodes[portion_named(g, "Purchase t2 -- Eggs")]["hasPerishabilityType"].id, "Fresh Meat")

    def test_what_cannot_be_booked(self):
        g = pantry()
        for kwargs in (dict(amount=0, unit="g"), dict(amount=2, unit="cup"), dict(amount=1, unit="g", storage="Attic")):
            with self.assertRaises(PantryError):
                buy(g, "Eggs", when=NOW, token="t1", **kwargs)
        self.assertFalse([n["name"] for n in g.nodes.values() if n["name"].startswith("Purchase")])


class UseAndCount(unittest.TestCase):
    def setUp(self):
        self.g = pantry()
        buy(self.g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        self.eggs = portion_named(self.g, "Purchase t1 -- Eggs")

    def test_use_takes_from_then_on(self):
        use(self.g, self.eggs, 150, "g", when(26, 8), "u1")
        self.assertEqual((grams(self.g, self.eggs, when(26, 7)), grams(self.g, self.eggs, when(26, 9))), (600.0, 450.0))

    def test_no_more_than_there_is(self):
        with self.assertRaises(PantryError):
            use(self.g, self.eggs, 601, "g", when(26, 8), "u1")

    def test_a_stock_take_is_the_new_baseline(self):
        use(self.g, self.eggs, 150, "g", when(26, 8), "u1")
        stock_take(self.g, self.eggs, 500, "g", when(26, 10), "s1")
        self.assertEqual(grams(self.g, self.eggs, when(26, 11)), 500.0)
        stock_take(self.g, self.eggs, 0, "g", when(26, 12), "s2")
        self.assertEqual(grams(self.g, self.eggs, when(26, 13)), 0.0)

    def test_discard_is_everything_left_and_on_record(self):
        use(self.g, self.eggs, 100, "g", when(26, 8), "u1")
        discard(self.g, self.eggs, when(26, 9), "d1")
        self.assertEqual(grams(self.g, self.eggs, when(26, 10)), 0.0)
        thrown = [n for n in self.g.nodes.values() if n["type"] == "Measurement" and n["name"] == "Discard d1 -- Purchase t1 -- Eggs amount"]
        self.assertEqual(thrown[0]["value"], 500.0)
        with self.assertRaises(PantryError):
            discard(self.g, self.eggs, when(26, 11), "d2")

    def test_opened_and_frozen_change_the_shelf_life(self):
        portion = lambda: self.g.get_all("PortionOfSubstance", self.eggs)["result"]
        open_portion(self.g, self.eggs)
        self.assertEqual(instance_expiration(self.g, portion(), when(26, 12)), (False, 1.0))   # 2 days opened
        open_portion(self.g, self.eggs)                                                         # again: no change
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        frozen = portion_named(g, "Purchase t1 -- Eggs")
        move(g, frozen, "Freezer")
        self.assertEqual(instance_expiration(g, g.get_all("PortionOfSubstance", frozen)["result"], when(26, 12)), (False, 179.0))

    def test_a_portion_in_no_container_gets_one_kept_as_it_was_taken_to_be(self):
        add_portion(self.g, "old eggs", "Eggs", 200.0, at(25, 0))
        open_portion(self.g, "old eggs")
        box = self.g.get_all("ContainerObject", self.g.nodes["old eggs"]["locatedIn"].id)["result"]
        self.assertEqual((box["hasStorageCondition"]["name"], box["hasOpenedStatus"]["name"]), ("Fridge", "Opened"))


class Cook(unittest.TestCase):
    def test_a_cook_draws_its_ingredients_soonest_to_expire_first(self):
        g = pantry()
        buy(g, "Eggs", 400, "g", when(20, 12), "old", keeps="Fresh Meat")      # expires on the 25th, 12:00
        buy(g, "Eggs", 600, "g", when(24, 12), "new", keeps="Fresh Meat")
        buy(g, "Noodles", 100, "g", NOW, "n")
        add_entry(g, "e1", "pasta", at(25, 9), servings=4.0)                   # 400 g of noodles, 200 g of eggs
        booking, short = cook(g, "e1", when(25, 10), "c1")
        old, new = portion_named(g, "Purchase old -- Eggs"), portion_named(g, "Purchase new -- Eggs")
        self.assertEqual((grams(g, old, when(25, 11)), grams(g, new, when(25, 11))), (200.0, 600.0))
        self.assertEqual([(s.food, s.needed, s.drawn) for s in short], [("Noodles", 400.0, 0.0)])   # bought after it
        self.assertEqual(g.nodes["e1"]["fulfilledBy"].id, f"Process:{booking.process}")
        with self.assertRaises(PantryError):
            cook(g, "e1", when(25, 10), "c2")

    def test_leftovers_need_nothing(self):
        g = pantry()
        add_entry(g, "e1", "pasta", at(25, 9), servings=2.0)
        add_entry(g, "e2", None, at(26, 9), leftover_of="e1")
        with self.assertRaises(PantryError):
            cook(g, "e2", when(26, 10), "c1")


if __name__ == "__main__":
    unittest.main()
