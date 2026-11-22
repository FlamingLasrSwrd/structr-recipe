"""Package sizes counted from FDC Branded Foods (mealplanner/fdc_packages.py, packages.apply_pin).

Worked out by hand.
  package_ounces: the first U.S. figure, as printed: "15 oz/425 g" 15, "16 OZ/1 LB/454 g" 16,
  "5 LBR" 5 x 16 = 80, "32 fl oz/1 Quart/946 mL" 32, "1 GAL/3.78 L" 128. Metric only: 500 mL /
  29.5735 = 16.90703, 454 g / 28.3495 = 16.01439, 1.5 kg / 28.3495 = 52.91098. No mass or volume:
  "12 CT", "1 EA", "", "0 oz".
  tally, rule Beans (category Canned, BLACK BEANS, not SOUP) over the fourteen products below:
  counted are 1-7 and 14 (8 is soup, 9 is a snack, 10 a count, 11 discontinued, 12 food service
  only, 13 not U.S.). Sizes: 15 (1, 2 and 3: 425 g is 14.991, to the quarter 15.0; owners Acme,
  whose two spellings are one, and Bolt), 15.5 (Cove), 63.75 (Dell's 1.81 kg is 63.846, to the
  quarter 63.75), 64 (Erin's 4 lb, Fern's 64 oz), 108 (Moss, food service AND grocery). Merging,
  most common first: 15 (3) and 64 (2) stay; 15.5 is 3.3% from 15 and stays; 63.75 is 0.4% from
  64 and joins it (3 products, 3 owners); 108 stays. Ordered by products, then owners: 64 (3, 3),
  15 (3, 2), 15.5 (1, 1), 108 (1, 1). In all 8 products from 7 owners. Rule Soup takes only 8.
  common_sizes, 30 products from 6 owners: 15 (12 products, 6 owners) is 40%, 15.5 (9, 5) 30%;
  29 (3, 3) is 10% but from 3 owners, 14 (6, 4) 20% from 4: both out. 19 products, or 4 owners,
  and nothing stands.
  apply_pin: Milk (estimate a gallon, 128 fl oz) counted 60 products from 20 owners: 128 (30, 10)
  50%, 64 (20, 8) 33%, 32 (6, 6) 10%, 16 (4, 4) 6.7%: a gallon, 64 fl oz and 32 fl oz, in fl_oz
  because the estimate is a volume. Flour (5 lb bag) 40 from 12: 80 (25, 9), 32 (15, 7), 16 (5, 5)
  12.5%: the 5 lb bag (80 oz is the estimate's size), 2 lb (32 oz, whole pounds from 2 lb), 16 oz.
  Oil (500 mL bottle, 16.9 fl oz) 30 from 10: 17 (20, 8) is 0.6% from 16.9, so the bottle as the
  estimate gives it; 33.75 (10, 5). Salt, 12 products, keeps its estimate.
  In a graph (tests/test_packages.py's, Milk 1.03 g/mL): 128 fl oz = 3898.97 g, 64 fl oz =
  64 x 29.5735 x 1.03 = 1949.49 g.
"""

import tomllib
import unittest

from mealplanner import fdc_packages as F
from mealplanner.packages import (
    PUBLIC_LEVEL, apply_pin, check_against_vocabulary, food_packages, import_packages, package_table, parse_packages,
    read_packages, read_pin,
)
from mealplanner.profiles import ProfileError
from tests.test_packages import BOOK, instance


def product(n, category, description, owner, weight, **extra):
    return {"n": n, "branded_food_category": category, "description": description, "brand_owner": owner,
            "package_weight": weight, "market_country": "United States", "discontinued_date": "", "trade_channel": "",
            **extra}


PRODUCTS = [
    product(1, "Canned Beans", "BLACK BEANS", "Acme Foods, Inc.", "15 oz/425 g"),
    product(2, "Canned Beans", "BLACK BEANS", "ACME FOODS INC.", "15 OZ"),
    product(3, "Canned Beans", "ORGANIC BLACK BEANS", "[[Bolt Co]]", "425 g"),
    product(4, "Canned Beans", "BLACK BEANS", "Cove", "15.5 oz"),
    product(5, "Canned Beans", "BLACK BEANS", "Dell", "1.81 kg"),
    product(6, "Canned Beans", "BLACK BEANS", "Erin", "4 lb"),
    product(7, "Canned Beans", "BLACK BEANS", "Fern", "64 oz"),
    product(8, "Canned Beans", "BLACK BEAN SOUP, BLACK BEANS", "Gale", "15 oz"),
    product(9, "Snacks", "BLACK BEANS", "Hale", "15 oz"),
    product(10, "Canned Beans", "BLACK BEANS", "Iris", "12 CT"),
    product(11, "Canned Beans", "BLACK BEANS", "Jade", "15 oz", discontinued_date="2024-01-01"),
    product(12, "Canned Beans", "BLACK BEANS", "Kite", "108 oz", trade_channel='["FOOD_SERVICE"]'),
    product(13, "Canned Beans", "BLACK BEANS", "Lark", "15 oz", market_country="New Zealand"),
    product(14, "Canned Beans", "BLACK BEANS", "Moss", "108 oz", trade_channel='["FOOD_SERVICE","GROCERY"]'),
]
RULES = {"Beans": {"category": "Canned", "match": r"\bBLACK BEANS\b", "exclude": "SOUP"},
         "Soup": {"category": "Canned", "match": "SOUP"}}

R = {food: {"category": food, "match": food.upper()} for food in ("Milk", "Flour", "Oil", "Salt")}
PIN = {"source": {"release": "2026-10-29"}, "foods": {
    "Milk": {"rule": R["Milk"], "products": 60, "owners": 20, "sizes": [[128, 30, 10], [64, 20, 8], [32, 6, 6], [16, 4, 4]]},
    "Flour": {"rule": R["Flour"], "products": 40, "owners": 12, "sizes": [[80, 25, 9], [32, 15, 7], [16, 5, 5]]},
    "Oil": {"rule": R["Oil"], "products": 30, "owners": 10, "sizes": [[17, 20, 8], [33.75, 10, 5]]},
    "Salt": {"rule": R["Salt"], "products": 12, "owners": 9, "sizes": [[26, 10, 8]]},
}}
COUNTED = {"package": [
    {"food": "Milk", "sizes": [[128, "fl_oz", "gallon"]], "fdc": R["Milk"]},
    {"food": "Flour", "sizes": [[5, "lb", "5 lb bag"]], "fdc": R["Flour"]},
    {"food": "Oil", "sizes": [[16.9, "fl_oz", "500 mL bottle"]], "fdc": R["Oil"]},
    {"food": "Salt", "sizes": [[26, "oz"]], "fdc": R["Salt"]},
    {"food": "Egg", "sizes": [[12, "each", "dozen"]]},
]}


def sized(entry):
    return [(s.amount, s.unit, s.label) for s in entry.sizes]


class Labels(unittest.TestCase):
    def test_the_first_us_figure_or_the_metric_one_converted(self):
        for text, ounces in (("15 oz/425 g", 15), ("16 OZ/1 LB/454 g", 16), ("5 LBR", 80), ("32 fl oz/1 Quart/946 mL", 32),
                             ("1 GAL/3.78 L", 128), ("15 oz.", 15), ("6.0 oz/170 g", 6)):
            with self.subTest(text=text):
                self.assertEqual(F.package_ounces(text), ounces)
        for text, ounces in (("500 mL", 16.90703), ("454 g", 16.01439), ("1.5 kg", 52.91098)):
            with self.subTest(text=text):
                self.assertAlmostEqual(F.package_ounces(text), ounces, places=4)
        for text in ("12 CT", "1 EA", "", "0 oz"):
            with self.subTest(text=text):
                self.assertIsNone(F.package_ounces(text))

    def test_to_the_quarter_ounce(self):
        self.assertEqual(F.size_bin(14.46), 14.5)
        self.assertEqual(F.size_bin(15.13), 15.25)


class Counting(unittest.TestCase):
    def test_one_count_per_food_of_the_products_a_shopper_finds(self):
        counts = F.tally(PRODUCTS, RULES)
        self.assertEqual(counts["Beans"], {"products": 8, "owners": 7, "sizes": [[64, 3, 3], [15, 3, 2], [15.5, 1, 1], [108, 1, 1]]})
        self.assertEqual(counts["Soup"], {"products": 1, "owners": 1, "sizes": [[15, 1, 1]]})

    def test_a_size_is_common_from_ten_percent_and_five_owners(self):
        count = {"products": 30, "owners": 6, "sizes": [[15, 12, 6], [15.5, 9, 5], [29, 3, 3], [14, 6, 4]]}
        self.assertEqual(F.common_sizes(count), [(15, 0.4, 12, 6), (15.5, 0.3, 9, 5)])
        self.assertEqual(F.common_sizes({**count, "products": 19}), [])
        self.assertEqual(F.common_sizes({**count, "owners": 4}), [])
        five = {"products": 100, "owners": 50, "sizes": [[s, 20, 10] for s in (1, 2, 3, 4, 5)]}
        self.assertEqual([s for s, *_ in F.common_sizes(five)], [1, 2, 3, 4])

    def test_a_rule_is_checked_where_it_is_written(self):
        bad = {"package": [{"food": "Egg", "sizes": [[12, "each"]], "fdc": {"category": "Eggs", "match": "EGG"}},
                           {"food": "A", "sizes": [[1, "g"]], "fdc": {"category": "(", "match": "A"}},
                           {"food": "B", "sizes": [[1, "g"]], "fdc": {"match": "B"}},
                           {"food": "C", "sizes": [[1, "g"]], "fdc": {"category": "c", "match": "C", "colour": 1}},
                           {"food": "D", "sizes": [[1, "g"]], "fdc": "D"}]}
        with self.assertRaises(ProfileError) as caught:
            parse_packages(bad)
        self.assertEqual(len(caught.exception.problems), 5, caught.exception.problems)


class FromThePin(unittest.TestCase):
    def test_counted_sizes_replace_the_estimate_and_keep_its_label_when_it_is_one(self):
        milk, flour, oil, salt, egg = apply_pin(parse_packages(COUNTED), PIN)
        self.assertEqual(sized(milk), [(128, "fl_oz", "gallon"), (64, "fl_oz", "64 fl oz"), (32, "fl_oz", "32 fl oz")])
        self.assertEqual(sized(flour), [(5, "lb", "5 lb bag"), (2, "lb", "2 lb"), (16, "oz", "16 oz")])
        self.assertEqual(sized(oil), [(16.9, "fl_oz", "500 mL bottle"), (33.75, "fl_oz", "33.75 fl oz")])
        self.assertEqual([milk.provenance, flour.provenance, oil.provenance], ["sourced"] * 3)
        self.assertEqual(milk.sizes[0].source, "FoodData Central Branded Foods (2026-10-29): 30 of 60 U.S. products (50%), "
                                               "from 10 of 20 brand owners, come in this size; public domain")

    def test_too_few_products_and_no_rule_keep_the_estimate(self):
        _, _, _, salt, egg = apply_pin(parse_packages(COUNTED), PIN)
        self.assertEqual((sized(salt), salt.provenance), ([(26, "oz", "26 oz")], ""))
        self.assertIn("too few products to count (12 from 9 brand owners)", salt.note)
        self.assertEqual((sized(egg), egg.provenance), ([(12, "each", "dozen")], ""))

    def test_a_rule_the_pin_was_not_counted_with_is_refused(self):
        changed = {"package": [{**COUNTED["package"][0], "fdc": {"category": "Milk", "match": "WHOLE MILK"}}]}
        unpinned = {"package": [{"food": "Cream", "sizes": [[8, "fl_oz"]], "fdc": {"category": "Cream", "match": "CREAM"}}]}
        for book in (changed, unpinned):
            with self.subTest(book=book), self.assertRaises(ProfileError):
                apply_pin(parse_packages(book), PIN)

    def test_loaded_as_sourced_with_the_count_and_the_rest_estimated(self):
        g = instance()
        book = {"package": [COUNTED["package"][0], COUNTED["package"][1]] + BOOK["package"][2:]}
        import_packages(g, apply_pin(parse_packages(book), PIN))
        gallon = g.nodes[f"DefaultSpecification:{PUBLIC_LEVEL} -- Milk -- gallon"]
        self.assertEqual(gallon["provenance"], "sourced")
        self.assertTrue(gallon["source"].startswith("FoodData Central Branded Foods (2026-10-29): 30 of 60"), gallon["source"])
        self.assertIn("128 fl_oz = 3898.97 g", gallon["source"])
        self.assertIn("64 fl_oz = 1949.49 g", g.nodes[f"DefaultSpecification:{PUBLIC_LEVEL} -- Milk -- 64 fl oz"]["source"])
        self.assertNotIn(f"DefaultSpecification:{PUBLIC_LEVEL} -- Flour -- 2 lb bag", g.nodes)    # the estimate's, pruned
        table = package_table(g, PUBLIC_LEVEL)
        self.assertEqual({p.label: p.estimated for p in food_packages(g, table, "Flour")},
                         {"5 lb bag": False, "2 lb": False, "16 oz": False})
        self.assertEqual([p.estimated for p in food_packages(g, table, "Egg")], [True])
        self.assertEqual(g.nodes[f"DefaultSpecification:{PUBLIC_LEVEL} -- Egg -- dozen"]["provenance"], "estimated")


class Shipped(unittest.TestCase):
    def test_the_pin_was_counted_with_the_shipped_rules_and_fits_the_vocabulary(self):
        entries = read_packages(".")
        pin = read_pin(".")
        self.assertEqual(set(pin["foods"]), {e.food for e in entries if e.fdc})
        resolved = apply_pin(entries, pin)
        with open("data/vocabulary.toml", "rb") as fh:
            self.assertEqual(check_against_vocabulary(resolved, tomllib.load(fh)), [])
        self.assertGreater(sum(1 for e in resolved if e.provenance == "sourced"), 100)


if __name__ == "__main__":
    unittest.main()
