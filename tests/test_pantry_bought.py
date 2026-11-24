"""A shopping line ticked and put into the pantry (pantry.buy_line, line_purchase, default_storage), and a
purchase taken back (pantry.unbuy), over tests/test_pantry.py's kitchen.

Expected values worked out by hand:
  - A line of three packages, 400, 400 and 200 g of eggs: three portions, "Purchase b1 -- Eggs", "... #2",
    "... #3", each in a container of its own, holding 400, 400 and 200 g; one Purchase Process.
  - Where it is kept: Frozen green peas (by name) and a product below them in the freezer; potatoes,
    which keep 30 days in the pantry and 7 in the fridge, in the pantry; grapes, 1 day in the pantry and 7
    in the fridge, in the fridge; milk, which FoodKeeper gives only a freezer time, in the fridge; eggs,
    with no shelf life of their own, in the fridge; a food below potatoes with none of its own, as
    potatoes, in the pantry.
  - A product of 12 oz (340.1940 g, 12 x 28.3495) chosen for a line that buys 900 g: 3 packages (900 /
    340.194 = 2.65, up); 2 when two are asked for.
"""

import json
import math
import unittest

from mealplanner.pantry import (PantryError, buy, buy_line, default_storage, line_purchase, purchase_nodes, record_name,
                                stock_take, unbuy, use)
from tests.fakegraph import Ref, when
from tests.planning_graph import add_type
from tests.test_packages import shelf
from tests.test_pantry import Graph as PantryGraph, grams, pantry, portion_named

NOW = when(25, 12)


class Graph(PantryGraph):
    """The pantry's graph, with what a purchase's portions are found by (thingsBegunDuring), and the
    participants of a Process kept on the portion's side too (processesWithParticipant)."""
    REVERSES = {**PantryGraph.REVERSES, "beginsToExistDuring": "thingsBegunDuring", "denotesType": "identifiers"}

    def _link(self, node_id, key, old, new):
        if key == "hasParticipant":
            for ref in new if isinstance(new, list) else []:
                self.nodes[ref.id].setdefault("processesWithParticipant", []).append(Ref(node_id))
            return
        super()._link(node_id, key, old, new)


def kitchen():
    g = Graph()
    g.nodes = pantry().nodes
    for name, parent in (("Frozen green peas", None), ("Peas 12 oz", "Frozen green peas"), ("Potatoes", None),
                         ("New potatoes", "Potatoes"), ("Grapes", None), ("Milk", None), ("PurchaseQuantity", None)):
        add_type(g, name, parent)
    shelf(g, "Potatoes", 30.0, "Pantry")
    shelf(g, "Potatoes", 7.0, "Fridge")
    shelf(g, "Grapes", 1.0, "Pantry")
    shelf(g, "Grapes", 7.0, "Fridge")
    shelf(g, "Milk", 90.0, "Freezer")
    shelf(g, "Milk", 5.0, "Fridge", "Opened")              # an opened figure says nothing of where it is kept sealed
    # Peas 12 oz: a product (a GTIN denotes it), one package holding 12 oz
    g.add("Concept", "GTIN", "GTIN")
    g.add("Identifier", "GTIN 00000000000017", "GTIN 00000000000017", identifierValue="00000000000017",
          identifierScheme=Ref("GTIN"), denotesType=Ref("Peas 12 oz"))
    g.add("QuantitySpecification", "Peas 12 oz package size value", value=12.0, unit="oz")
    g.add("DefaultSpecification", "Peas 12 oz package size", forType=Ref("Peas 12 oz"), hasKind=Ref("PurchaseQuantity"),
          keyedBy=[], hasValue=Ref("Peas 12 oz package size value"))
    g.nodes["Peas 12 oz"]["defaultSpecifications"].append(Ref("Peas 12 oz package size"))
    return g


def named(g, type_name, prefix):
    return sorted(n["name"] for n in g.nodes.values() if n["type"] == type_name and n["name"].startswith(prefix))


def storage_of(g, portion_name):
    box = g.nodes[portion_named(g, portion_name)]["locatedIn"]
    return g.nodes[box.id]["hasStorageCondition"].id


class WhereItIsKept(unittest.TestCase):
    def test_frozen_by_name_else_where_it_keeps_longest_of_the_fridge_and_the_pantry(self):
        g = kitchen()
        for food, where in (("Frozen green peas", "Freezer"), ("Peas 12 oz", "Freezer"), ("Potatoes", "Pantry"),
                            ("New potatoes", "Pantry"), ("Grapes", "Fridge"), ("Milk", "Fridge"), ("Eggs", "Fridge")):
            self.assertEqual(default_storage(g, food), where, food)

    def test_a_line_that_names_no_place_is_kept_where_its_food_keeps(self):
        g = kitchen()
        buy_line(g, "Frozen green peas", [300.0], NOW, "f1")
        buy_line(g, "Potatoes", [1000.0], NOW, "p1")
        buy_line(g, "Potatoes", [1000.0], NOW, "p2", storage="Fridge")      # the line said so
        self.assertEqual([storage_of(g, n) for n in ("Purchase f1 -- Frozen green peas", "Purchase p1 -- Potatoes",
                                                     "Purchase p2 -- Potatoes")], ["Freezer", "Pantry", "Fridge"])


class APurchaseFromTheList(unittest.TestCase):
    def test_each_package_is_a_portion_of_its_own(self):
        g = kitchen()
        booking = buy_line(g, "Eggs", [400.0, 400.0, 200.0], NOW, "b1")
        names = named(g, "PortionOfSubstance", "Purchase b1")
        self.assertEqual(names, ["Purchase b1 -- Eggs", "Purchase b1 -- Eggs #2", "Purchase b1 -- Eggs #3"])
        self.assertEqual([grams(g, portion_named(g, n), NOW) for n in names], [400.0, 400.0, 200.0])
        self.assertEqual(len({g.nodes[portion_named(g, n)]["locatedIn"].id for n in names}), 3)
        self.assertEqual(named(g, "Process", "Purchase b1"), ["Purchase b1"])
        self.assertEqual((booking.process, booking.notes[0]), ("Purchase b1", "Eggs: 3 packages, 1,000 g, kept in the fridge"))
        for n in names:
            self.assertEqual(g.nodes[portion_named(g, n)]["beginsToExistDuring"].id, "Process:Purchase b1")

    def test_one_piece_is_written_as_buy_writes_a_purchase(self):
        a, b = kitchen(), kitchen()
        buy_line(a, "Eggs", [600.0], NOW, "t1")
        buy(b, "Eggs", 600, "g", NOW, "t1")
        shape = lambda g: sorted((n["type"], n["name"]) for n in g.nodes.values() if n["name"].startswith("Purchase t1"))  # noqa: E731
        self.assertEqual(shape(a), shape(b))

    def test_opening_one_package_opens_no_other(self):
        g = kitchen()
        buy_line(g, "Eggs", [300.0, 300.0], NOW, "b1")
        use(g, portion_named(g, "Purchase b1 -- Eggs"), 100, "g", when(26, 8), "u1")
        opened = [g.nodes[g.nodes[portion_named(g, n)]["locatedIn"].id]["hasOpenedStatus"].id
                  for n in ("Purchase b1 -- Eggs", "Purchase b1 -- Eggs #2")]
        self.assertEqual(opened, ["Opened", "Sealed"])

    def test_the_same_line_twice_writes_nothing_new(self):
        g = kitchen()
        buy_line(g, "Eggs", [300.0, 300.0], NOW, "b1")
        posts = g.posts
        self.assertEqual(buy_line(g, "Eggs", [300.0, 300.0], NOW, "b1").created, [])
        self.assertEqual(g.posts, posts)

    def test_its_class_is_the_last_portions_of_the_food(self):
        g = kitchen()
        buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        self.assertEqual(buy_line(g, "Eggs", [300.0], NOW, "b1").notes, ["Eggs: 300 g, kept in the fridge"])
        self.assertEqual(g.nodes[portion_named(g, "Purchase b1 -- Eggs")]["hasPerishabilityType"].id, "Fresh Meat")

    def test_no_shelf_life_is_said(self):
        g = kitchen()
        self.assertEqual(buy_line(g, "Milk", [1000.0], NOW, "m1").notes,
                         ["Milk: 1,000 g, kept in the fridge", "Milk: no shelf life known for it in the fridge, so no expiry"])

    def test_what_cannot_be_put_away(self):
        g = kitchen()
        for pieces, storage in (([], None), ([0.0], None), ([-5.0], None), ([math.nan], None), ([math.inf], None),
                                ([100.0], "Attic"), ([1.0] * 100, None)):
            with self.assertRaises(PantryError, msg=(pieces[:2], storage)):
                buy_line(g, "Eggs", pieces, NOW, "x1", storage=storage)
        self.assertEqual(named(g, "Process", "Purchase x1"), [])


class WhatALineAsks(unittest.TestCase):
    def test_the_lines_own_packages_or_other_grams(self):
        g = kitchen()
        self.assertEqual(line_purchase(g, "Eggs", pieces="400,400,200.5"), ("Eggs", [400.0, 400.0, 200.5]))
        self.assertEqual(line_purchase(g, "Eggs", pieces="400,400", grams="250"), ("Eggs", [250.0]))
        self.assertEqual(line_purchase(g, "Eggs", pieces=[120.0]), ("Eggs", [120.0]))

    def test_a_product_of_its_food_so_many_packages_or_enough(self):
        g = kitchen()
        food, pieces = line_purchase(g, "Frozen green peas", pieces="900", product="Peas 12 oz", buy="900")
        self.assertEqual((food, len(pieces)), ("Peas 12 oz", 3))
        self.assertAlmostEqual(pieces[0], 340.194)
        self.assertEqual(len(line_purchase(g, "Frozen green peas", product="Peas 12 oz", count="2", buy="900")[1]), 2)
        self.assertEqual(len(line_purchase(g, "Frozen green peas", product="Peas 12 oz", buy="")[1]), 1)     # at least one

    def test_what_a_line_cannot_ask(self):
        g = kitchen()
        for kwargs in (dict(food="Eggs", product="Peas 12 oz"),                   # not a product of eggs
                       dict(food="Frozen green peas", product="Potatoes"),       # no product at all
                       dict(food="Frozen green peas", product="Peas 12 oz", count="1.5"),
                       dict(food="Frozen green peas", product="Peas 12 oz", count="0"),
                       dict(food="Frozen green peas", product="Peas 12 oz", count="many"),
                       dict(food="Frozen green peas", product="Peas 12 oz", count="100")):
            with self.assertRaises(PantryError, msg=kwargs):
                line_purchase(g, **kwargs)
        food, pieces = line_purchase(g, "Eggs", grams="lots")                     # read as nothing: buy_line refuses it
        with self.assertRaises(PantryError):
            buy_line(g, food, pieces, NOW, "x1")


class TakenBack(unittest.TestCase):
    def test_every_node_it_wrote_goes_after_a_record_of_them_is_kept(self):
        g = kitchen()
        # its own nodes, not the Pantry Operation kinds the first purchase made, which are shared and stay
        wrote = [n for n in buy_line(g, "Eggs", [400.0, 200.0], NOW, "b1", by=None).created if n.startswith("Purchase b1")]
        self.assertEqual(len(wrote), 10)                   # a Process, its time, and four nodes a package
        kept = []
        booking = unbuy(g, "b1", when(25, 13), keep=lambda name, text: kept.append((name, json.loads(text))))
        self.assertEqual(sorted(booking.created), sorted(wrote))
        self.assertFalse([n for n in g.nodes.values() if n["name"].startswith("Purchase b1")])
        self.assertIn("Purchase", named(g, "DomainType", "Purchase"))   # the kind stays
        ((name, record),) = kept
        self.assertEqual(name, record_name("b1", when(25, 13)))
        self.assertEqual(name, "undone Purchase b1 20260925T130000.json")
        self.assertEqual((record["undone"], record["at"], record["by"]), ("Purchase b1", "2026-09-25T13:00:00+0000", None))
        self.assertEqual(sorted(n["name"] for n in record["nodes"]), sorted(wrote))
        bought = next(n for n in record["nodes"] if n["name"] == "Purchase b1 -- Eggs #2 mass bought")
        self.assertEqual((bought["value"], bought["unit"], bought["isAboutQuality"]["name"]),
                         (200.0, "g", "Purchase b1 -- Eggs #2 mass Quality"))
        portion = next(n for n in record["nodes"] if n["name"] == "Purchase b1 -- Eggs")
        self.assertEqual((portion["instanceOf"]["name"], portion["beginsToExistDuring"]["name"]), ("Eggs", "Purchase b1"))

    def test_a_buy_from_the_pantry_page_can_be_taken_back_too(self):
        g = kitchen()
        buy(g, "Eggs", 600, "g", NOW, "t1")
        unbuy(g, "t1", NOW)
        self.assertFalse([n for n in g.nodes.values() if n["name"].startswith("Purchase t1")])

    def test_once_something_rests_on_it_it_stays(self):
        for after in ("use", "count", "move"):
            g = kitchen()
            buy_line(g, "Eggs", [300.0, 300.0], NOW, "b1")
            second = portion_named(g, "Purchase b1 -- Eggs #2")
            if after == "use":
                use(g, second, 10, "g", when(26, 8), "u1")
            elif after == "count":
                stock_take(g, second, 290, "g", when(26, 8), "s1")
            else:
                from mealplanner.pantry import move
                move(g, second, "Freezer", when(26, 8), "m1")
            before = len(g.nodes)
            with self.assertRaises(PantryError, msg=after) as said:
                unbuy(g, "b1", when(26, 9), keep=lambda *_: self.fail("a record of what was not undone"))
            self.assertIn("stays", str(said.exception))
            self.assertEqual(len(g.nodes), before, after)

    def test_what_is_no_purchase(self):
        g = kitchen()
        with self.assertRaises(PantryError):
            unbuy(g, "nope", NOW)
        buy(g, "Eggs", 600, "g", NOW, "t1")
        use(g, portion_named(g, "Purchase t1 -- Eggs"), 10, "g", when(26, 8), "u1")
        with self.assertRaises(PantryError):              # a Use's Process is no purchase
            purchase_nodes(g, "u1")
        unbuy_twice = kitchen()
        buy(unbuy_twice, "Eggs", 600, "g", NOW, "t1")
        unbuy(unbuy_twice, "t1", NOW)
        with self.assertRaises(PantryError):
            unbuy(unbuy_twice, "t1", NOW)


if __name__ == "__main__":
    unittest.main()
