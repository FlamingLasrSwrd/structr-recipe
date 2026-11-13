"""Products and their barcodes (mealplanner/products.py, tools/import_products.py, tools/pantry.py scan).

The barcodes are published examples, each check digit worked by hand (from the right the other digits
weigh 3, 1, 3, ...; the check digit brings the sum to a multiple of ten):

  UPC-A   03600029145|2     3 x (5+1+2+0+6+0) + (4+9+0+0+3) = 42 + 16 = 58 -> 2
  EAN-13  400638133393|1    3 x (3+3+3+8+6+0) + (9+3+1+3+0+4) = 69 + 20 = 89 -> 1
  EAN-8   7351353|7         3 x (3+3+5+7) + (5+1+3) = 54 + 9 = 63 -> 7
  UPC-E   0 425261 4        its last digit of six is 1, so maker 04 2 1 00, item 00 526: UPC-A 04210000526|4,
                            3 x (6+5+0+0+2+0) + (2+0+0+1+4) = 39 + 7 = 46 -> 4
  GTIN-14 1003600029145|9   3 x (5+1+2+0+6+0+1) + (4+9+0+0+3+0) = 45 + 16 = 61 -> 9
  a shop's own: UPC-A 21234567899|2 (3 x 31 + 25 = 118), UPC-A 41234567890|3 (3 x 28 + 13 = 97),
                EAN-13 201234567890|3 (3 x 24 + 15 = 87), EAN-8 2012345|1 (3 x 11 + 6 = 39)

The foods: Eggs (an egg weighs 50 g here), Milk (1.03 g per mL), Noodles, and a group, Beans, that
Chickpeas and Black beans sit under. So a dozen eggs is 12 x 50 = 600 g, and a litre of milk 1,030 g.
Milk keeps 7 days sealed in the fridge.
"""

import io
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from mealplanner.identifier_schema import GTIN, SCHEME_CONCEPTS
from mealplanner.inventory import instance_expiration, physical_on_hand
from mealplanner.pantry import PantryError, buy
from mealplanner.products import (
    Product, ProductError, buyable, check_digit, find, import_products, normalize, parse_products, product_ids,
)
from tests.fakegraph import Ref, when
from tests.planning_graph import add_type
from tests.test_pantry import Graph as PantryGraph, pantry
from tools import check_pages, import_products as products_tool
from tools import pantry as pantry_tool

NOW = when(25, 12)
UPC_A, EAN_13, EAN_8, UPC_E, GTIN_14 = "036000291452", "4006381333931", "73513537", "04252614", "10036000291459"
DOZEN = Product("Farm eggs dozen", "Eggs", ("00036000291452",), 12.0, "each")
MILK = Product("Dairy milk 1 L", "Milk", ("04006381333931", "00000073513537"), 1.0, "l")


class Graph(PantryGraph):
    REVERSES = {**PantryGraph.REVERSES, "hierarchy": "domainTypes", "identifierScheme": "identifiersInScheme",
                "denotesType": "identifiers"}

    def wait_until_ready(self):
        pass


def kitchen():
    g = Graph()
    g.nodes = pantry().nodes
    g.add("TypeHierarchy", "Food Identity", domainTypes=[])
    for name, parent in (("Food", None), ("Milk", "Food"), ("Beans", "Food"), ("Chickpeas", "Beans"),
                         ("Black beans", "Beans"), ("PurchaseQuantity", None)):
        add_type(g, name, parent)
    for name in ("Eggs", "Noodles"):
        g.nodes[name]["parent"] = Ref("Food")
        g.nodes["Food"]["children"].append(Ref(name))
    for name in ("Food", "Eggs", "Noodles", "Milk", "Beans", "Chickpeas", "Black beans"):
        g.nodes[name]["hierarchy"] = Ref("Food Identity")
        g.nodes["Food Identity"]["domainTypes"].append(Ref(name))
    for food, kind, value, unit, keys in (("Eggs", "MassPerUnit", 50.0, "g_per_each", []),
                                          ("Milk", "Density", 1.03, "g_per_mL", []),
                                          ("Milk", "ShelfLife", 7.0, "days", ["Fridge", "Sealed"])):
        g.add("QuantitySpecification", f"{food} {kind} value", value=value, unit=unit)
        g.add("DefaultSpecification", f"{food} {kind}", hasKind=Ref(kind), keyedBy=[Ref(k) for k in keys],
              hasValue=Ref(f"{food} {kind} value"))
        g.nodes[food]["defaultSpecifications"].append(Ref(f"{food} {kind}"))
    return g


def named(g, type_name):
    return sorted(n["name"] for n in g.nodes.values() if n["type"] == type_name)


def problems_of(call, *args):
    try:
        call(*args)
    except ProductError as exc:
        return exc.problems
    raise AssertionError("no problem was found")


class Barcodes(unittest.TestCase):
    def test_the_check_digit(self):
        for body, digit in (("03600029145", 2), ("400638133393", 1), ("7351353", 7), ("04210000526", 4),
                            ("1003600029145", 9)):
            self.assertEqual(check_digit(body), digit, body)

    def test_every_length_is_one_gtin_of_fourteen_digits(self):
        self.assertEqual(normalize(UPC_A), "00036000291452")
        self.assertEqual(normalize(EAN_13), "04006381333931")
        self.assertEqual(normalize(EAN_8), "00000073513537")
        self.assertEqual(normalize(GTIN_14), "10036000291459")

    def test_a_upc_a_is_the_same_number_however_it_is_written(self):
        for written in ("0 36000 29145 2", "0-36000-29145-2", "0036000291452", "00036000291452"):
            self.assertEqual(normalize(written), "00036000291452", written)

    def test_a_short_upc_e_is_spelled_out_to_its_upc_a(self):
        self.assertEqual(normalize(UPC_E), "00042100005264")
        # the other three shapes, each checked against the UPC-A's own check digit:
        #   last of six 3: 0 123453 C -> 0 123 00000 45 C; 3 x (5+0+0+0+2+0) + (4+0+0+3+1) = 21 + 8 = 29 -> 1
        #   last of six 4: 0 123454 C -> 0 1234 00000 5 C; 3 x (5+0+0+4+2+0) + (0+0+0+3+1) = 33 + 4 = 37 -> 3
        #   last of six 7: 0 123457 C -> 0 12345 0000 7 C; 3 x (7+0+0+4+2+0) + (0+0+5+3+1) = 39 + 9 = 48 -> 2
        #   last of six 0: 0 123450 C -> 0 12 0 0000 345 C; 3 x (5+3+0+0+2+0) + (4+0+0+0+1) = 30 + 5 = 35 -> 5
        #   last of six 2: 0 123452 C -> 0 12 2 0000 345 C; 3 x (5+3+0+0+2+0) + (4+0+0+2+1) = 30 + 7 = 37 -> 3
        #   number system 1: 1 425261 C -> 1 42 1 0000 526 C; 3 x (6+5+0+0+2+1) + (2+0+0+1+4) = 42 + 7 = 49 -> 1
        self.assertEqual(normalize("01234505"), "00012000003455")
        self.assertEqual(normalize("01234523"), "00012200003453")
        self.assertEqual(normalize("14252611"), "00142100005261")
        self.assertEqual(normalize("01234531"), "00012300000451")
        self.assertEqual(normalize("01234543"), "00012340000053")
        self.assertEqual(normalize("01234572"), "00012345000072")

    def test_what_is_not_a_products_barcode(self):
        for barcode, why in (("036000291453", "its last digit should be 2"), ("03600029145", "has 11 digits"),
                             ("03600029145x", "is not a number"), ("", "is not a number"),
                             ("212345678992", "a shop's own number"), ("412345678903", "a shop's own number"),
                             ("2012345678903", "a shop's own number"), ("20123451", "a shop's own number"),
                             (36000291452, "has 11 digits")):       # unquoted in the file, its leading zero is lost
            with self.assertRaises(ValueError) as caught:
                normalize(barcode)
            self.assertIn(why, str(caught.exception), barcode)

    def test_a_country_that_starts_with_four_is_not_a_shops_own(self):
        self.assertEqual(normalize(EAN_13)[1:3], "40")        # 400 to 440 is Germany; 04 after the padding is a shop's


class TheFile(unittest.TestCase):
    ROW = {"name": "Farm eggs dozen", "food": "Eggs", "barcodes": ["0 36000 29145 2"], "amount": 12, "unit": "each"}

    def test_a_product_as_the_file_states_it(self):
        self.assertEqual(parse_products({"product": [self.ROW]}), [DOZEN])

    def test_a_barcode_written_twice_is_one(self):
        row = {**self.ROW, "barcodes": [UPC_A, "0036000291452"]}
        self.assertEqual(parse_products({"product": [row]}), [DOZEN])

    def test_every_problem_is_named(self):
        rows = [
            {**self.ROW, "barcodes": []},
            {**self.ROW, "name": "Eggs", "barcodes": [EAN_13]},
            {**self.ROW, "name": "Six eggs", "barcodes": [UPC_A], "amount": 0},
            {**self.ROW, "name": "Bad unit", "barcodes": [UPC_A], "unit": "box"},
            {**self.ROW, "name": "A, B", "barcodes": [UPC_E]},
            {**self.ROW, "name": "Misread", "barcodes": ["036000291453"], "shelf": "top"},
            {"food": "Eggs"},
        ]
        problems = problems_of(parse_products, {"product": rows, "shop": {}})
        for expected in ("sections it does not use: shop", "Farm eggs dozen: it lists no barcode",
                         "Eggs: a product is named apart from its food", "Six eggs: what a package holds (amount) must be more than 0",
                         "Bad unit: barcode '036000291452' is also Six eggs's", "Bad unit: unit 'box' is not one of",
                         "A, B: a name cannot hold a comma", "Misread: barcode '036000291453' is misread or mistyped",
                         "Misread: it has fields it does not use: shelf", "a product has no name"):
            self.assertTrue(any(expected in p for p in problems), (expected, problems))
        self.assertEqual(len(problems), 10, problems)

    def test_a_name_twice(self):
        problems = problems_of(parse_products, {"product": [self.ROW, {**self.ROW, "barcodes": [EAN_13]}]})
        self.assertEqual(problems, ["Farm eggs dozen: named twice"])


class Load(unittest.TestCase):
    def test_a_product_is_a_type_below_its_food_that_its_barcodes_denote(self):
        g = kitchen()
        counts = import_products(g, [DOZEN, MILK])
        eggs = g.get_all("DomainType", "DomainType:Farm eggs dozen")["result"]
        self.assertEqual((eggs["parent"]["name"], eggs["hierarchy"]["name"], eggs["isLookupBearing"]),
                         ("Eggs", "Food Identity", True))
        self.assertEqual(named(g, "Identifier"), ["GTIN 00000073513537", "GTIN 00036000291452", "GTIN 04006381333931"])
        code = g.get_all("Identifier", "Identifier:GTIN 00036000291452")["result"]
        self.assertEqual((code["identifierValue"], code["identifierScheme"]["name"], code["denotesType"]["name"]),
                         ("00036000291452", "GTIN", "Farm eggs dozen"))
        size = g.get_all("DefaultSpecification", "DefaultSpecification:Farm eggs dozen package size")["result"]
        value = g.get_all("QuantitySpecification", size["hasValue"]["id"])["result"]
        self.assertEqual((size["hasKind"]["name"], size["forType"]["name"], size["provenance"], value["value"], value["unit"]),
                         ("PurchaseQuantity", "Farm eggs dozen", "sourced", 12.0, "each"))
        # the scheme and its Concept, then for each product a Type, its barcodes, a size and its value: 2 + 4 + 5
        self.assertEqual(counts, {"created": 11, "changed": 0, "unchanged": 0, "deleted": 0})
        self.assertEqual(product_ids(g), {"DomainType:Farm eggs dozen", "DomainType:Dairy milk 1 L"})
        for node in g.nodes.values():
            if node["id"].split(":")[0] in ("DomainType", "Identifier", "DefaultSpecification", "QuantitySpecification",
                                            "Concept", "ConceptScheme") and ":" in node["id"]:
                self.assertEqual((node["visibleToAuthenticatedUsers"], node["visibleToPublicUsers"]), (True, False), node["id"])

    def test_twice_writes_nothing_new(self):
        g = kitchen()
        import_products(g, [DOZEN, MILK])
        posts, patches = g.posts, g.patches
        self.assertEqual(import_products(g, [DOZEN, MILK]), {"created": 0, "changed": 0, "unchanged": 11, "deleted": 0})
        self.assertEqual((g.posts, g.patches), (posts, patches))

    def test_the_scheme_is_not_one_the_build_seeds(self):
        self.assertNotIn(GTIN, SCHEME_CONCEPTS)               # so tools/expected_state.json is as it was

    def test_a_barcode_the_file_no_longer_lists_is_removed_and_a_new_size_replaces_the_old(self):
        g = kitchen()
        import_products(g, [DOZEN, MILK])
        two_litres = Product(MILK.name, "Milk", ("04006381333931",), 2.0, "l")
        self.assertEqual(import_products(g, [DOZEN, two_litres]), {"created": 0, "changed": 1, "unchanged": 9, "deleted": 1})
        self.assertEqual(named(g, "Identifier"), ["GTIN 00036000291452", "GTIN 04006381333931"])
        self.assertIsNone(find(g, EAN_8))
        self.assertEqual((find(g, EAN_13).amount, find(g, EAN_13).unit), (2.0, "l"))

    def test_a_barcode_moved_to_another_product_of_the_file_is_that_ones_whichever_comes_first(self):
        moved = [Product(DOZEN.name, "Eggs", ("00036000291452", "00000073513537"), 12.0, "each"),
                 Product(MILK.name, "Milk", ("04006381333931",), 1.0, "l")]
        for order in (moved, moved[::-1]):
            g = kitchen()
            import_products(g, [DOZEN, MILK])
            counts = import_products(g, order)
            self.assertEqual(find(g, EAN_8).product, "Farm eggs dozen", order[0].name)
            self.assertEqual(len(named(g, "Identifier")), 3)
            self.assertEqual(counts["created"] + counts["changed"] - counts["deleted"], 1, counts)   # moved, however

    def test_a_product_left_out_of_the_file_stays(self):
        g = kitchen()
        import_products(g, [DOZEN, MILK])
        import_products(g, [MILK])
        self.assertEqual(find(g, UPC_A).product, "Farm eggs dozen")

    def test_what_cannot_be_loaded_is_named_and_nothing_is_written(self):
        g = kitchen()
        import_products(g, [DOZEN])
        posts, patches = g.posts, g.patches
        bad = [
            Product("Shop eggs six", "Egg", ("04006381333931",), 6.0, "each"),            # no such food
            Product("Tinned beans", "Beans", ("00000073513537",), 400.0, "g"),            # a group
            Product("Half dozen", "Farm eggs dozen", ("00042100005264",), 6.0, "each"),   # a product below a product
            Product("Milk", "Eggs", ("10036000291459",), 500.0, "g"),                     # already a food
            Product("Other eggs", "Eggs", ("00036000291452",), 12.0, "each"),             # Farm eggs dozen's barcode
            Product("Noodle nests", "Noodles", ("00012300000451",), 6.0, "each"),         # no weight per item
            Product("Purchase kind", "PurchaseQuantity", ("00012340000053",), 1.0, "g"),  # not in the Food Identity hierarchy
        ]
        problems = problems_of(import_products, g, bad)
        for expected in ("Shop eggs six: 'Egg' is not a food of this instance",
                         "Tinned beans: 'Beans' is a group of foods (Black beans, Chickpeas), not a food that is bought",
                         "Half dozen: 'Farm eggs dozen' is a product itself",
                         "Milk: that name is already a food here, not a product",
                         "Other eggs: barcode 00036000291452 already belongs to 'Farm eggs dozen', which this file does not name",
                         "Noodle nests: 6 each of Noodles does not convert to grams",
                         "Purchase kind: 'PurchaseQuantity' is not a food of this instance"):
            self.assertTrue(any(p.startswith(expected) for p in problems), (expected, problems))
        self.assertEqual(len(problems), 7, problems)
        self.assertEqual((g.posts, g.patches), (posts, patches))

    def test_a_second_product_of_a_food_is_not_stopped_by_the_first(self):
        g = kitchen()
        import_products(g, [DOZEN])
        import_products(g, [Product("Shop eggs six", "Eggs", ("00042100005264",), 6.0, "each")])
        self.assertEqual(find(g, UPC_E).food, "Eggs")

    def test_an_instance_without_the_kind_says_so(self):
        g = kitchen()
        del g.nodes["PurchaseQuantity"]
        self.assertIn("no 'PurchaseQuantity' kind of default", problems_of(import_products, g, [DOZEN])[0])


class Find(unittest.TestCase):
    def setUp(self):
        self.g = kitchen()
        import_products(self.g, [DOZEN, MILK])

    def test_a_barcode_names_its_product_food_and_package(self):
        found = find(self.g, "0 36000 29145 2")
        self.assertEqual((found.gtin, found.product, found.food, found.amount, found.unit),
                         ("00036000291452", "Farm eggs dozen", "Eggs", 12.0, "each"))
        self.assertEqual(find(self.g, "0036000291452"), found)                 # the same, read as an EAN-13
        self.assertEqual(find(self.g, EAN_8).product, "Dairy milk 1 L")

    def test_an_unknown_barcode_names_nothing(self):
        self.assertIsNone(find(self.g, UPC_E))

    def test_the_same_digits_in_another_scheme_are_not_a_barcode(self):
        add_type(self.g, "Somewhere")
        self.g.post("/structr/rest/Concept", {"name": "FDC ID"})
        self.g.post("/structr/rest/Identifier", {"name": "an FDC id", "identifierValue": "00042100005264",
                                                 "identifierScheme": "Concept:FDC ID", "denotesType": "Somewhere"})
        self.assertIsNone(find(self.g, UPC_E))

    def test_a_barcode_two_products_share_is_a_problem(self):
        self.g.post("/structr/rest/Identifier", {"name": "a copy", "identifierValue": "00036000291452",
                                                 "identifierScheme": "Concept:GTIN", "denotesType": "DomainType:Dairy milk 1 L"})
        self.assertIn("names 2 products: Dairy milk 1 L, Farm eggs dozen", problems_of(find, self.g, UPC_A)[0])


class InThePantry(unittest.TestCase):
    """A product is its food to everything that walks the hierarchy."""

    def setUp(self):
        self.g = kitchen()
        import_products(self.g, [DOZEN, MILK])

    def test_a_product_bought_is_stock_of_its_food_weighed_by_the_foods_own_figures(self):
        buy(self.g, "Eggs", 600, "g", NOW, "loose")
        pantry_tool.scan(self.g, UPC_A, 2, NOW, "t1")
        pantry_tool.scan(self.g, EAN_13, 1, NOW, "t1")
        self.assertEqual(physical_on_hand(self.g, "DomainType:Farm eggs dozen", NOW), 1200.0)    # 2 x 12 x 50 g
        self.assertEqual(physical_on_hand(self.g, "Eggs", NOW), 1800.0)                          # and the 600 g loose
        self.assertAlmostEqual(physical_on_hand(self.g, "Milk", NOW), 1030.0)                    # 1 L x 1.03 g per mL
        (portion,) = [n for n in self.g.nodes.values() if n["name"] == "Purchase t1 -- Farm eggs dozen"]
        self.assertEqual(portion["instanceOf"].id, "DomainType:Farm eggs dozen")

    def test_a_product_keeps_as_long_as_its_food(self):
        booking = pantry_tool.scan(self.g, EAN_13, 1, NOW, "t1")
        (portion,) = [n for n in self.g.nodes.values() if n["name"] == "Purchase t1 -- Dairy milk 1 L"]
        row = self.g.get_all("PortionOfSubstance", portion["id"])["result"]
        self.assertEqual(instance_expiration(self.g, row, when(27, 12)), (False, 5.0))    # milk: 7 days sealed in the fridge
        self.assertEqual(booking.notes, ["Dairy milk 1 L: 1 x 1 l"])                      # so no "no shelf life known"

    def test_a_scan_says_what_it_bought_and_twice_is_once(self):
        first = pantry_tool.scan(self.g, UPC_A, 2, NOW, "t1", storage="Pantry")
        self.assertEqual(first.notes[0], "Farm eggs dozen: 2 x 12 each")
        self.assertEqual(pantry_tool.scan(self.g, UPC_A, 2, NOW, "t1", storage="Pantry").created, [])
        self.assertEqual(physical_on_hand(self.g, "Eggs", NOW), 1200.0)

    def test_what_a_scan_cannot_book(self):
        for barcode, packages, why in ((UPC_E, 1, "no product has barcode 00042100005264"),
                                       ("036000291453", 1, "misread or mistyped"), (UPC_A, 0, "the number of packages must be more than 0")):
            with self.assertRaises(PantryError) as caught:
                pantry_tool.scan(self.g, barcode, packages, NOW, "t1")
            self.assertIn(why, str(caught.exception))
        self.assertEqual(physical_on_hand(self.g, "Eggs", NOW), 0.0)

    def test_a_food_with_only_products_below_it_is_still_bought_and_so_are_they(self):
        self.assertEqual(buyable(self.g), ["Black beans", "Chickpeas", "Dairy milk 1 L", "Eggs", "Farm eggs dozen",
                                           "Milk", "Noodles"])            # not Food or Beans: groups

    def test_before_any_product_it_is_the_foods_nothing_sits_under(self):
        self.assertEqual(buyable(kitchen()), ["Black beans", "Chickpeas", "Eggs", "Milk", "Noodles"])

    def test_the_page_is_checked_against_it(self):
        offered = ["Black beans", "Chickpeas", "Dairy milk 1 L", "Farm eggs dozen", "Milk", "Noodles", "Beans"]
        problems = []
        with mock.patch.object(check_pages, "buy_data", return_value=offered):
            self.assertEqual(check_pages.check_buyable(self.g, self.g, problems), 7)
        self.assertEqual(problems, ["pantry: Eggs can be bought, but Buy does not offer it",
                                    "pantry: Buy offers Beans, which is a group of foods or no food"])

    def test_the_page_reads_the_same_scheme(self):
        page = (pathlib.Path(__file__).resolve().parents[1] / "pages" / "pantry.js").read_text()
        self.assertIn(f'$.find("Concept", {{name: "{GTIN}"}})', page)
        self.assertIn('id=\\"buy-data\\"', page)


class TheTool(unittest.TestCase):
    FILE = ('[[product]]\nname = "Farm eggs dozen"\nfood = "Eggs"\nbarcodes = ["0 36000 29145 2"]\namount = 12\n'
            'unit = "each"\n')

    def run_tool(self, g, *argv, text=None):
        said = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(products_tool, "connect", return_value=g), \
                redirect_stdout(said):
            path = os.path.join(tmp, "products.toml")
            with open(path, "w") as fh:
                fh.write(self.FILE if text is None else text)
            code = products_tool.main([a if a != "FILE" else path for a in argv])
        return code, said.getvalue()

    def test_check_reads_no_instance(self):
        self.assertEqual(self.run_tool(None, "FILE", "--check"), (0, "1 product(s), 1 barcode(s)\n"))

    def test_load_then_find(self):
        g = kitchen()
        code, said = self.run_tool(g, "FILE")
        self.assertEqual((code, said.splitlines()[-1]), (0, "created 6, changed 0, unchanged 0, deleted 0"))
        self.assertEqual(self.run_tool(g, "--find", UPC_A),
                         (0, "00036000291452: Farm eggs dozen (Eggs), 12 each a package\n"))
        self.assertEqual(self.run_tool(g, "--find", EAN_13), (1, "no product has barcode 04006381333931\n"))

    def test_problems_are_printed_and_fail(self):
        code, said = self.run_tool(kitchen(), "FILE", text=self.FILE.replace('"Eggs"', '"Beans"'))
        self.assertEqual(code, 1)
        self.assertIn("problem: Farm eggs dozen: 'Beans' is a group of foods", said)
        code, said = self.run_tool(None, "FILE", "--check", text=self.FILE.replace("29145 2", "29145 3"))
        self.assertEqual((code, said), (1, "problem: Farm eggs dozen: barcode '0 36000 29145 3' is misread or mistyped: "
                                           "its last digit should be 2\n"))
        self.assertEqual(self.run_tool(None, "--find", "12")[0], 1)


if __name__ == "__main__":
    unittest.main()
