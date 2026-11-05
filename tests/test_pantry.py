"""Pantry bookings (mealplanner/pantry.py), read back through the inventory engine (inventory.py).

The kitchen is tests/test_planning_extract.py's: an omelette (yield 2) takes 300 g of eggs; pasta
(yield 2) takes 200 g of noodles and 100 g of eggs. Eggs are Fresh Meat here, for a shelf life:
5 days sealed in the fridge, 2 opened, 180 sealed in the freezer.
"""

import io
import pathlib
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

from mealplanner.inventory import instance_expiration
from mealplanner.pantry import (USED_UP_G, PantryError, buy, cook, discard, move, on_hand, open_portion, person_named,
                                signed_in_person, stock_take, use)
from tests.fakegraph import Ref, WritableGraph, at, when
from tests.planning_graph import add_entry, add_portion, add_type
from tests.test_planning_extract import kitchen
from tools import check_pages
from tools import pantry as pantry_tool

NOW = when(25, 12)


class Graph(WritableGraph):
    """The write side, with the relationships the pantry writes kept in both directions."""
    RELATIONS = WritableGraph.RELATIONS | {
        "process", "hasActualQuantity", "occupiesTemporalRegion", "beginsToExistDuring", "locatedIn",
        "hasStorageCondition", "hasOpenedStatus", "hasPerishabilityType", "concretizes", "fulfills", "fulfilledBy",
        "isAbout", "wasAssociatedWith"}
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


class UsedUp(unittest.TestCase):
    """A Use typed as the rounded amount shown leaves a crumb: 32 fl oz of broth is 996.0005 g, shown as
    "996 g", and 996 g used leaves 0.0005 g, which stayed in the pantry as "0 g", expired, for good."""

    def left(self, bought, used):
        g = pantry()
        buy(g, "Eggs", bought, "g", NOW, "t1", keeps="Fresh Meat")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        use(g, eggs, used, "g", when(25, 13), "t2")
        return g, eggs

    def page_says(self, g, *shown):
        problems = []
        rows = [{"portion": "Purchase t1 -- Eggs", "grams": grams_shown, "days": None} for grams_shown in shown]
        with mock.patch.object(check_pages, "page_data", return_value=rows):
            counted = check_pages.check_pantry(g, g, problems)
        return counted, problems

    def test_a_crumb_is_used_up_and_the_page_leaves_it_out(self):
        g, _ = self.left(996.0005, 996)
        self.assertEqual(self.page_says(g), (0, []))

    def test_a_page_still_showing_a_crumb_is_a_difference(self):
        g, _ = self.left(996.0005, 996)
        counted, problems = self.page_says(g, 0.0005)
        self.assertEqual(counted, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("is shown, but nothing of it is known to be on hand", problems[0])

    def test_half_a_gram_shows_as_a_gram_so_it_is_still_on_hand(self):
        g, _ = self.left(100.5, 100)
        counted, problems = self.page_says(g)
        self.assertEqual(counted, 1)
        self.assertIn("is on hand (0.5 g) but not shown", problems[0])

    def test_the_terminal_list_leaves_a_crumb_out_and_keeps_a_gram(self):
        for used, listed in ((996, False), (995, True)):
            g, _ = self.left(996.0005, used)
            said = io.StringIO()
            with redirect_stdout(said):
                pantry_tool.show(g, None, when(25, 14))
            self.assertEqual("Purchase t1 -- Eggs" in said.getvalue(), listed, used)

    def test_the_pages_use_the_same_number(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        engine = re.search(r"const USED_UP_G = ([0-9.]+);", (root / "pages" / "lib" / "30_stock.js").read_text())
        self.assertEqual(float(engine.group(1)), USED_UP_G)
        self.assertIn("level[0] < USED_UP_G", (root / "pages" / "pantry.js").read_text())


class WhoBooked(unittest.TestCase):
    """Each booking's Process names the Person who made it (wasAssociatedWith, data-model.md K1)."""

    def setUp(self):
        self.g = pantry()
        self.g.add("Person", "Jamie")
        self.g.add("Person", "Alex")

    def who(self, process_name):
        (row,) = [n for n in self.g.nodes.values() if n["type"] == "Process" and n["name"] == process_name]
        return sorted(ref.id for ref in row.get("wasAssociatedWith") or [])

    def test_a_purchase_a_use_a_discard_and_a_cook_name_who_made_them(self):
        buy(self.g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat", by="Jamie")
        eggs = portion_named(self.g, "Purchase t1 -- Eggs")
        use(self.g, eggs, 100, "g", when(25, 13), "u1", by="Alex")
        discard(self.g, eggs, when(25, 14), "d1", by="Jamie")
        add_entry(self.g, "e1", "omelette", at(25, 9), servings=2.0)
        booking, _ = cook(self.g, "e1", when(25, 15), "c1", by="Alex")
        self.assertEqual([self.who(name) for name in ("Purchase t1", "Use u1", "Discard d1", booking.process)],
                         [["Jamie"], ["Alex"], ["Jamie"], ["Alex"]])

    def test_no_one_given_names_no_one(self):
        buy(self.g, "Eggs", 600, "g", NOW, "t1")
        self.assertEqual(self.who("Purchase t1"), [])

    def test_a_booking_repeated_by_someone_else_is_still_the_first_ones(self):
        buy(self.g, "Eggs", 600, "g", NOW, "t1", by="Jamie")
        self.assertEqual(buy(self.g, "Eggs", 600, "g", NOW, "t1", by="Alex").created, [])
        self.assertEqual(self.who("Purchase t1"), ["Jamie"])

    def test_a_person_by_name(self):
        self.assertEqual(person_named(self.g, "Jamie"), "Jamie")
        with self.assertRaises(PantryError):
            person_named(self.g, "Sam")
        self.g.add("Person", "Jamie 2", name="Jamie")
        with self.assertRaises(PantryError):
            person_named(self.g, "Jamie")

    def test_the_signed_in_person_is_only_a_person(self):
        class Me:
            def __init__(self, row):
                self.row = row

            def get(self, path, params=None):
                assert path == "/structr/rest/me"
                return {"result": self.row}
        self.assertEqual(signed_in_person(Me({"id": "p1", "type": "Person", "name": "Jamie"})), "p1")
        self.assertIsNone(signed_in_person(Me({"id": "u1", "type": "User", "name": "mealplanner-tools"})))
        self.assertEqual(signed_in_person(Me([{"id": "p1", "type": "Person"}])), "p1")

    def test_the_pages_name_the_signed_in_person_on_every_process(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        engine = (root / "pages" / "lib" / "40_bookings.js").read_text()
        self.assertIn('const BOOKED_BY = $.me && $.me.type === "Person" ? $.me.id : null;', engine)
        self.assertIn("wasAssociatedWith: bookedBy()", engine.split("function bookProcess", 1)[1].split("\n}", 1)[0])


class RoundedUp(unittest.TestCase):
    """The pantry shows whole grams, so the amount shown can be up to half a gram more than there is: a Use
    within USED_UP_G of what a portion holds, either way, is all of it. Worked by hand: 996.6 g shows as
    "997 g"; 997 g used is 0.4 g more than there is, so it draws the 996.6 g."""

    def after(self, bought, used):
        g = pantry()
        buy(g, "Eggs", bought, "g", NOW, "t1", keeps="Fresh Meat")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        use(g, eggs, used, "g", when(25, 13), "u1")
        (drawn,) = [n["value"] for n in g.nodes.values() if n["type"] == "Measurement" and n["name"] == "Use u1 -- Purchase t1 -- Eggs amount"]
        return grams(g, eggs, when(25, 14)), drawn

    def test_the_amount_shown_rounded_up_is_all_of_it(self):
        self.assertEqual(self.after(996.6, 997), (0.0, 996.6))

    def test_half_a_gram_over_is_all_of_it(self):
        self.assertEqual(self.after(996.5, 997), (0.0, 996.5))

    def test_one_that_would_leave_a_crumb_is_all_of_it(self):
        self.assertEqual(self.after(996.4, 996), (0.0, 996.4))

    def test_half_a_gram_left_is_still_left(self):
        self.assertEqual(self.after(100.5, 100), (0.5, 100.0))

    def test_more_than_half_a_gram_over_is_refused(self):
        with self.assertRaises(PantryError):
            self.after(996.4, 997)

    def test_nothing_is_taken_from_what_is_used_up(self):
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1", keeps="Fresh Meat")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        use(g, eggs, 600, "g", when(25, 13), "u1")
        with self.assertRaises(PantryError):
            use(g, eggs, 0.4, "g", when(25, 14), "u2")

    def test_the_pages_have_the_same_rule(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        use_action = (root / "pages" / "lib" / "50_pantry.js").read_text().split("  use: ", 1)[1].split("\n  },", 1)[0]
        self.assertIn("if (have - grams >= -USED_UP_G && have - grams < USED_UP_G) take = have;", use_action)
        self.assertIn("if (!(have > 0))", use_action)


if __name__ == "__main__":
    unittest.main()
