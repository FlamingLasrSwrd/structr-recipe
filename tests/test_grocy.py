"""The Grocy import (mealplanner/grocy.py, tools/import_grocy.py, docs/imports.md) over the export in
tests/fixtures/grocy and its map.

The expected values were worked out by hand from the fixture files, not by running the code:

  Eggs         10 Piece; a Piece is an item; no conversion to a mass   -> 10 each, the Fridge
  Tomato       4 Piece; its own 1 Piece = 120 Gram                     -> 480 g, the Fridge
  Milk         1.5 Bottle; its own 1 Bottle = 1 Liter, 1 Liter = 1030 Gram -> 1545 g, the Fridge, opened
  Minced meat  2 Pack; its own 1 Pack = 500 Gram                       -> 1000 g, Chest freezer (flagged) = Freezer
  Flour        750 Gram                                                -> 750 g, the Pantry
  Sugar        0.5 Pack; its own 1 Pack = 1 Kilogram, every product's 1 Kilogram = 1000 Gram -> 500 g, the Pantry
  Chocolate, Gummy bears: no food in the map; Pickles: "" (not a food); Bananas: kept in the Fruit bowl,
  which the map does not place. Old cereal is inactive. Best-before dates other than Grocy's 2999-12-31:
  entries 1-4 and 7-10, 8 of them; prices: entries 1, 2, 3, 4, 6, 7, 6 of them.
"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from mealplanner import grocy
from mealplanner.pantry import on_hand
from tests.fakegraph import Ref, WritableGraph
from tests.planning_graph import add_type, new_kitchen
from tools import import_grocy

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "grocy"
MAP = FIXTURES / "map.toml"
ZONE = ZoneInfo("America/Edmonton")


def export():
    return grocy.read_export(str(FIXTURES))


def vocabulary():
    return grocy.read_vocabulary_foods(str(ROOT / "data" / "vocabulary.toml"))


def fixture_plan(mapping=None):
    return grocy.plan(export(), mapping or grocy.read_mapping(str(MAP)), vocabulary())


def small_export(conversions, products=(("A", 1), ("B", 1))):
    """Units Piece (1) and Gram (2); products named in order from id 1."""
    return grocy.parse_export({
        "quantity_units": [{"id": 1, "name": "Piece", "name_plural": "Pieces"}, {"id": 2, "name": "Gram", "name_plural": "Grams"}],
        "products": [{"id": i, "name": name, "qu_id_stock": unit, "location_id": 1} for i, (name, unit) in enumerate(products, 1)],
        "locations": [{"id": 1, "name": "Fridge", "is_freezer": 0}],
        "quantity_unit_conversions": [{"from_qu_id": f, "to_qu_id": t, "factor": x, "product_id": p} for f, t, x, p in conversions],
        "stock": []})


class Units(unittest.TestCase):
    def test_a_grocy_unit_is_ours_only_by_its_name(self):
        units = {u.name: u.ours for u in export().units.values()}
        self.assertEqual(units, {"Piece": "each", "Pack": None, "Glass": None, "Tin": None, "Gram": "g",
                                 "Kilogram": "kg", "Liter": "l", "Milliliter": "ml", "Bottle": None})

    def test_a_unit_named_in_the_singular_alone_is_ours_too(self):
        self.assertEqual((grocy.Unit(1, "Piece", None).ours, grocy.Unit(2, "Litre", None).kind, grocy.Unit(3, "Tin", None).ours),
                         ("each", "volume", None))

    def test_numbers_given_as_strings_by_an_older_grocy_read_the_same(self):
        old = grocy.parse_export({
            "quantity_units": [{"id": "1", "name": "Gram", "name_plural": "Grams"}],
            "products": [{"id": "4", "name": "Flour", "qu_id_stock": "1", "location_id": "1", "active": "1"}],
            "locations": [{"id": "1", "name": "Pantry", "is_freezer": "0"}],
            "quantity_unit_conversions": [],
            "stock": [{"id": "5", "product_id": "4", "amount": "750", "purchased_date": "2026-09-01",
                       "best_before_date": "2999-12-31", "open": "0", "location_id": "1", "stock_id": "x", "price": ""}]})
        (entry,) = old.stock
        self.assertEqual((entry.amount, entry.purchased, entry.best_before, entry.price, entry.opened),
                         (750.0, date(2026, 9, 1), None, None, False))
        self.assertEqual(grocy.quantity(old, entry), (750.0, "g"))

    def test_an_export_naming_a_unit_it_does_not_hold_is_refused(self):
        with self.assertRaises(grocy.GrocyError):
            small_export([(1, 9, 5, None)])


class Quantities(unittest.TestCase):
    def amounts(self):
        e = export()
        return {e.products[s.product].name: grocy.quantity(e, s) for s in e.stock}

    def test_each_stock_amount_in_grams_where_grocy_reaches_a_mass(self):
        a = self.amounts()
        self.assertEqual((a["Tomato"], a["Milk"], a["Minced meat"], a["Flour"], a["Sugar"]),
                         ((480.0, "g"), (1545.0, "g"), (1000.0, "g"), (750.0, "g"), (500.0, "g")))

    def test_items_where_it_reaches_none_and_nothing_where_it_reaches_no_unit_of_ours(self):
        a = self.amounts()
        self.assertEqual((a["Eggs"], a["Pickles"], a["Gummy bears"]), ((10.0, "each"), None, None))

    def test_a_products_own_conversion_stands_in_for_the_general_one(self):
        e = small_export([(1, 2, 50, None), (1, 2, 120, 1)])
        self.assertEqual((grocy.per_unit(e, 1, 1, "mass"), grocy.per_unit(e, 2, 1, "mass")), (120.0, 50.0))

    def test_a_conversion_is_read_backwards_too(self):
        e = small_export([(2, 1, 0.008, 1)])               # 1 Gram = 0.008 Piece: a Piece is 125 g
        self.assertAlmostEqual(grocy.per_unit(e, 1, 1, "mass"), 125.0)

    def test_another_products_conversion_does_not_apply(self):
        e = small_export([(1, 2, 120, 2)])
        self.assertIsNone(grocy.per_unit(e, 1, 1, "mass"))


class Facts(unittest.TestCase):
    def test_what_the_conversions_state_for_the_vocabulary(self):
        got = {(f.product, f.kind, f.unit): (f.grams, f.general) for f in grocy.facts(export())}
        self.assertEqual(got, {("Chocolate", "each", "Piece"): (100.0, False), ("Tomato", "each", "Piece"): (120.0, False),
                               ("Milk", "density", "Liter"): (1.03, False), ("Milk", "package", "Bottle"): (1030.0, False),
                               ("Minced meat", "package", "Pack"): (500.0, False), ("Sugar", "package", "Pack"): (1000.0, False)})


class Matching(unittest.TestCase):
    def test_only_a_product_the_map_names_is_matched(self):
        p = fixture_plan()
        self.assertEqual(p.matched, {"Eggs": "Egg", "Tomato": "Tomato", "Milk": "Whole milk", "Flour": "AP Flour",
                                     "Minced meat": "Ground beef 85% lean (raw)", "Sugar": "Granulated sugar",
                                     "Bananas": "Banana"})
        self.assertEqual(sorted(p.proposed), ["Chocolate", "Cookies", "Gummy bears"])
        self.assertEqual((p.not_food, p.inactive, p.problems), (["Pickles"], ["Old cereal"], []))

    def test_without_a_map_nothing_is_matched_or_booked_even_under_the_same_name(self):
        p = fixture_plan(grocy.Mapping({}, {}))
        self.assertEqual((p.matched, p.bookings), ({}, []))
        self.assertEqual(p.proposed["Tomato"][0], "Tomato")          # proposed, first, and still not taken

    def test_a_group_of_foods_is_never_proposed_or_accepted(self):
        self.assertNotIn("Eggs", fixture_plan(grocy.Mapping({}, {})).proposed["Eggs"])
        p = fixture_plan(grocy.Mapping({"Eggs": "Eggs"}, {}))
        self.assertNotIn("Eggs", p.matched)
        self.assertEqual(len(p.problems), 1)
        self.assertIn("a group of foods", p.problems[0])

    def test_a_map_naming_a_product_the_export_lacks_is_a_problem(self):
        p = fixture_plan(grocy.Mapping({"Bread": "Whole wheat bread"}, {}))
        self.assertEqual(p.problems, ["the map names a product the export does not hold: 'Bread'"])

    def test_a_map_storage_that_is_not_one_of_the_three_is_refused(self):
        with self.assertRaises(grocy.GrocyError):
            grocy.parse_mapping({"locations": {"Cellar": "Cellar"}})

    def test_the_draft_fills_in_only_the_same_name_and_keeps_what_the_map_says(self):
        draft = grocy.draft_map(export(), vocabulary(), grocy.Mapping({"Milk": "Whole milk"}, {"Fruit bowl": "Pantry"}))
        live = [line for line in draft.splitlines() if line and not line.startswith("#") and "=" in line]
        self.assertEqual(live, ['"Milk" = "Whole milk"', '"Tomato" = "Tomato"      # the same name: check it',
                                '"Fruit bowl" = "Pantry"'])
        self.assertIn('# "Candy cupboard" =', draft)


class Locations(unittest.TestCase):
    def test_a_freezer_by_grocys_flag_the_three_by_name_and_the_rest_by_the_map(self):
        self.assertEqual(fixture_plan().storage, {
            "Candy cupboard": ("Pantry", "the map"), "Chest freezer": ("Freezer", "Grocy marks it a freezer"),
            "Fridge": ("Fridge", "its name"), "Fruit bowl": (None, "not in the map"), "Pantry": ("Pantry", "its name"),
            "Tinned food cupboard": ("Pantry", "the map")})


class ThePlan(unittest.TestCase):
    def test_the_purchases_it_would_book(self):
        got = [(b.product, b.food, b.amount, b.unit, b.storage, b.purchased, b.opened, b.token) for b in fixture_plan().bookings]
        self.assertEqual(got, [
            ("Eggs", "Egg", 10.0, "each", "Fridge", date(2026, 10, 30), False, "grocy 6720a1b2c3d41"),
            ("Tomato", "Tomato", 480.0, "g", "Fridge", date(2026, 11, 1), False, "grocy 6720a1b2c3d42"),
            ("Milk", "Whole milk", 1545.0, "g", "Fridge", date(2026, 10, 31), True, "grocy 6720a1b2c3d43"),
            ("Minced meat", "Ground beef 85% lean (raw)", 1000.0, "g", "Freezer", date(2026, 10, 15), False, "grocy 6720a1b2c3d44"),
            ("Flour", "AP Flour", 750.0, "g", "Pantry", date(2026, 9, 1), False, "grocy 6720a1b2c3d45"),
            ("Sugar", "Granulated sugar", 500.0, "g", "Pantry", date(2026, 9, 20), False, "grocy 6720a1b2c3d46")])

    def test_what_it_would_not_book_and_why(self):
        self.assertEqual(fixture_plan().not_booked, [
            (7, "Chocolate", "no food confirmed for it in the map"), (8, "Pickles", "not a food here (the map)"),
            (9, "Gummy bears", "no food confirmed for it in the map"),
            (10, "Bananas", "no storage condition for 'Fruit bowl' in the map")])

    def test_what_is_left_for_a_later_stage_is_counted(self):
        self.assertEqual(fixture_plan().later, {"best-before dates": 8, "prices": 6})

    def test_a_purchase_is_booked_at_the_start_of_its_day_where_the_owner_lives(self):
        b = fixture_plan().bookings[0]
        self.assertEqual(b.when(ZONE), datetime(2026, 10, 30, 0, 0, tzinfo=ZONE))


class Graph(WritableGraph):
    """The write side, with the relationships pantry.buy and open_portion write (as tests/test_pantry.py's)."""
    RELATIONS = WritableGraph.RELATIONS | {
        "occupiesTemporalRegion", "beginsToExistDuring", "locatedIn", "hasStorageCondition", "hasOpenedStatus",
        "hasPerishabilityType"}


def instance():
    """The six foods the fixture books, an Egg weighing 50 g, and nothing about shelf lives."""
    g = Graph()
    g.nodes = new_kitchen().nodes
    for name in ("Sealed", "Opened", "Fridge", "Freezer", "Pantry", "ShelfLife", "Density", "MassPerUnit"):
        add_type(g, name)
    for food in ("Egg", "Tomato", "Whole milk", "Ground beef 85% lean (raw)", "AP Flour", "Granulated sugar"):
        add_type(g, food)
    g.add("QuantitySpecification", "Egg each value", value=50.0, unit="g_per_each", status="default")
    g.add("DefaultSpecification", "Egg each", forType=Ref("Egg"), hasKind=Ref("MassPerUnit"), keyedBy=[],
          hasValue=Ref("Egg each value"))
    g.nodes["Egg"]["defaultSpecifications"].append(Ref("Egg each"))
    return g


def portion(g, name):
    (row,) = [n for n in g.nodes.values() if n["type"] == "PortionOfSubstance" and n["name"] == name]
    return g.get_all("PortionOfSubstance", row["id"])["result"]


class Booking(unittest.TestCase):
    def test_each_purchase_is_booked_through_the_pantry_and_reads_back_as_stock(self):
        g, p = instance(), fixture_plan()
        results = grocy.book(g, p, ZONE)
        self.assertEqual([r.problem for r in results], [None] * 6)
        later = datetime(2026, 11, 4, 12, tzinfo=ZONE)
        grams = {b.food: on_hand(g, portion(g, b.portion()), later) for b in p.bookings}
        self.assertEqual(grams, {"Egg": 500.0, "Tomato": 480.0, "Whole milk": 1545.0, "Ground beef 85% lean (raw)": 1000.0,
                                 "AP Flour": 750.0, "Granulated sugar": 500.0})
        boxes = {b.food: g.nodes[portion(g, b.portion())["locatedIn"]["id"]] for b in p.bookings}
        self.assertEqual({f: (box["hasStorageCondition"].id, box["hasOpenedStatus"].id) for f, box in boxes.items()}, {
            "Egg": ("Fridge", "Sealed"), "Tomato": ("Fridge", "Sealed"), "Whole milk": ("Fridge", "Opened"),
            "Ground beef 85% lean (raw)": ("Freezer", "Sealed"), "AP Flour": ("Pantry", "Sealed"),
            "Granulated sugar": ("Pantry", "Sealed")})
        self.assertIsNone(on_hand(g, portion(g, p.bookings[1].portion()), datetime(2026, 10, 31, 23, tzinfo=ZONE)))

    def test_importing_the_same_export_twice_writes_nothing_new(self):
        g, p = instance(), fixture_plan()
        grocy.book(g, p, ZONE)
        posts = g.posts
        self.assertEqual([r.created for r in grocy.book(g, p, ZONE)], [0] * 6)
        self.assertEqual(g.posts, posts)

    def test_a_purchase_the_instance_refuses_is_reported_and_the_rest_go_on(self):
        g = instance()
        del g.nodes["AP Flour"]                         # a food the map names that the instance lacks
        results = grocy.book(g, fixture_plan(), ZONE)
        self.assertEqual([r.buy.product for r in results if r.problem], ["Flour"])
        self.assertEqual(sum(1 for r in results if r.created), 5)


class Tool(unittest.TestCase):
    def run_tool(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("mealplanner.connection.connect",
                                              side_effect=AssertionError("the check read an instance")):
            code = import_grocy.main([str(FIXTURES), *argv])
        return code, out.getvalue()

    def test_the_check_reports_matches_and_non_matches_and_reads_no_instance(self):
        code, out = self.run_tool("--map", str(MAP), "--check")
        self.assertEqual(code, 0)
        self.assertIn("matched      Milk -> Whole milk   (the map)", out)
        self.assertIn("not matched  Chocolate: alike in the vocabulary, for review: Semisweet chocolate chips", out)
        self.assertIn("not matched  Gummy bears: nothing alike in the vocabulary", out)
        self.assertIn("Purchases it would book: 6", out)
        self.assertIn("entry 10 (Bananas): no storage condition for 'Fruit bowl' in the map", out)
        self.assertIn("Left for a later stage: 8 best-before dates, 6 prices, the shopping list, recipes", out)

    def test_a_map_with_a_problem_fails_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "map.toml"
            bad.write_text('[foods]\n"Eggs" = "Eggs"\n')
            code, out = self.run_tool("--map", str(bad), "--check")
        self.assertEqual(code, 1)
        self.assertIn("problem: Eggs: the map names 'Eggs', a group of foods", out)

    def test_booking_without_a_time_zone_stops_before_any_instance(self):
        code, out = self.run_tool("--map", str(MAP))
        self.assertEqual(code, 1)
        self.assertIn("booking needs --timezone", out)

    def test_fetch_records_each_object_and_sends_the_key(self):
        sent = []

        def opener(request):
            sent.append((request.full_url, request.get_header("Grocy-api-key")))
            return io.BytesIO(json.dumps([{"id": 1}]).encode())

        with tempfile.TemporaryDirectory() as tmp:
            written = import_grocy.fetch("https://grocy.example/", os.path.join(tmp, "x"), "k", opener)
            self.assertEqual(sorted(os.path.basename(w) for w in written), sorted(f"{o}.json" for o in grocy.OBJECTS))
            self.assertEqual(json.loads(pathlib.Path(written[0]).read_text()), [{"id": 1}])
        self.assertEqual(sent, [(f"https://grocy.example/api/objects/{o}", "k") for o in grocy.OBJECTS])


if __name__ == "__main__":
    unittest.main()
