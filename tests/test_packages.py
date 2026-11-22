"""What foods are sold in (mealplanner/packages.py) and the shopping list rounded up to it (shopping.py).

Worked out by hand.
  choose: sizes 400 g and 800 g. 850 g: three 400s and 800 + 400 both leave 350 g, and 800 + 400 is
  fewer packages, so (1, 1). 800 g: one 800 leaves nothing, as two 400s do in more packages: (0, 1).
  401 g: two 400s leave 399 g, one 800 leaves 399 g in one package: (0, 1). Listed 800 g first, 850 g
  is still one of each, (1, 1), not (0, 3), though that has fewer of the size listed first.
The levels: "US" sells Flour in a 2 lb (907.184 g) and a 5 lb (2267.96 g) bag, Milk in a gallon
(128 fl oz x 29.5735 mL x 1.03 g/mL = 3898.970 g) and Egg by the dozen (12 x 50 g = 600 g). "Home",
below it, sells Flour only in a 1 kg bag: its Flour replaces both of US's, and its Milk is US's.
Butter (salted) has no size of its own and takes its parent Butter's.
The shopping list is tests/test_shopping.py's week: buy 450 g of eggs and 200 g of noodles. Eggs are
sold in 300 g and 600 g boxes: one 600 g box leaves 150 g, as two 300 g boxes do in more packages.
Noodles come in a 340 g bag: 140 g left. At $0.50 and $0.30 per 100 g: eggs $3.00 bought, $0.75 of
it left; noodles $1.02 bought, $0.42 left; $4.02 in all, $1.17 left over.
Eggs keep 3 days in the fridge once opened, so what is left of them keeps from their first use,
Mon 28 Sep 18:00, to Thu 1 Oct 18:00. Noodles have no opened figure: they keep 730 days unopened in
the pantry (where they keep longest), also from their first use, Tue 29 Sep 2026 18:00, to Thu 28 Sep
2028 (2028 has a 29 February).
"""

import tomllib
import unittest
from datetime import timedelta, timezone

from mealplanner.packages import (
    HOME_LEVEL, PUBLIC_LEVEL, Package, check_against_vocabulary, choose, default_level, food_packages, import_packages,
    instantiate_packages, package_table, parse_packages, read_packages,
)
from mealplanner.profiles import ProfileError
from mealplanner.shopping import Line, _round_up, describe, shopping_list
from tests.fakegraph import Ref, WritableGraph, when
from tests.test_shopping import NOW, priced, week

BOOK = {"package": [
    {"food": "Flour", "sizes": [[2, "lb", "2 lb bag"], [5, "lb", "5 lb bag"]]},
    {"food": "Milk", "sizes": [[128, "fl_oz", "gallon"]]},
    {"food": "Egg", "sizes": [[12, "each", "dozen"]]},
    {"food": "Butter", "sizes": [[1, "lb"]]},
]}


def instance(book=BOOK):
    g = WritableGraph()
    for h in ("Default Kind", "Food Identity"):
        g.add("TypeHierarchy", h, h)
    for kind in ("Density", "MassPerUnit", "PurchaseQuantity"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Default Kind"), defaultSpecifications=[])
    for food in ("Flour", "Egg", "Milk", "Butter", "Salt"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), defaultSpecifications=[])
    g.add("DomainType", "Butter (salted)", "Butter (salted)", hierarchy=Ref("Food Identity"), parent=Ref("Butter"),
          defaultSpecifications=[])
    for food, kind, value, unit in (("Milk", "Density", 1.03, "g_per_mL"), ("Egg", "MassPerUnit", 50.0, "g_per_each")):
        g.add("QuantitySpecification", f"{food} {kind} value", value=value, unit=unit, status="default")
        g.add("DefaultSpecification", f"{food} {kind}", forType=Ref(food), hasKind=Ref(kind), keyedBy=[],
              hasValue=Ref(f"{food} {kind} value"))
        g.nodes[food]["defaultSpecifications"].append(Ref(f"{food} {kind}"))
    import_packages(g, parse_packages(book))
    return g


def home(g, own=None):
    return instantiate_packages(g, {"name": HOME_LEVEL, "profile": PUBLIC_LEVEL,
                                    "own": own if own is not None else {"Flour": {"sizes": [[1, "kg", "1 kg bag"]]}}})


def sizes(g, level, food):
    return [(p.label, p.amount, p.unit) for p in food_packages(g, package_table(g, level), food)]


class Choose(unittest.TestCase):
    def test_least_left_over_then_fewest_packages(self):
        self.assertEqual(choose([400.0, 800.0], 850.0), (1, 1))
        self.assertEqual(choose([800.0, 400.0], 850.0), (1, 1))       # not three 400s, though they come first by count
        self.assertEqual(choose([400.0, 800.0], 800.0), (0, 1))
        self.assertEqual(choose([400.0, 800.0], 401.0), (0, 1))
        self.assertEqual(choose([400.0], 1200.0), (3,))

    def test_a_need_within_rounding_of_a_package_is_one_package(self):
        self.assertEqual(choose([400.0], 400.0003), (1,))
        self.assertEqual(choose([400.0], 400.01), (2,))

    def test_on_a_tie_the_sizes_listed_first_are_bought_least(self):
        self.assertEqual(choose([300.0, 300.0], 300.0), (0, 1))

    def test_nothing_needed_buys_nothing(self):
        self.assertEqual(choose([400.0, 800.0], 0.0), (0, 0))


class Definitions(unittest.TestCase):
    def test_every_problem_is_reported(self):
        bad = {"package": [{"food": "A"}, {"food": "B", "sizes": [[0, "g"]]}, {"food": "C", "sizes": [[1, "furlong"]]},
                           {"food": "D", "sizes": [[1, "g", "a, b"]]}, {"food": "E", "sizes": [[1, "g", "x"], [2, "g", "x"]]},
                           {"food": "A", "sizes": [[1, "g"]]}, {"food": "F", "sizes": [[1, "g"]], "colour": 1},
                           {"food": "G", "sizes": [[1, "g"]] * 5}]}
        with self.assertRaises(ProfileError) as caught:
            parse_packages(bad)
        self.assertEqual(len(caught.exception.problems), 8)

    def test_a_label_defaults_to_the_size(self):
        (entry,) = parse_packages({"package": [{"food": "A", "sizes": [[14.5, "fl_oz"]]}]})
        self.assertEqual(entry.sizes[0].label, "14.5 fl oz")

    def test_the_vocabulary_must_give_what_a_size_needs(self):
        vocabulary = {"food": [{"name": "Milk", "volume": "cup"}, {"name": "Cream", "parent": "Milk"}, {"name": "Salt"},
                               {"name": "Egg", "each": "large"}]}
        entries = parse_packages({"package": [
            {"food": "Cream", "sizes": [[1, "cup"]]}, {"food": "Salt", "sizes": [[1, "cup"], [1, "each"], [1, "lb"]]},
            {"food": "Egg", "sizes": [[12, "each"]]}, {"food": "Nothing", "sizes": [[1, "g"]]}]})
        problems = check_against_vocabulary(entries, vocabulary)
        self.assertEqual(len(problems), 3, problems)          # Salt's cup and each, and Nothing; Cream takes Milk's density

    def test_the_shipped_file_fits_the_shipped_vocabulary(self):
        with open("data/vocabulary.toml", "rb") as fh:
            self.assertEqual(check_against_vocabulary(read_packages("."), tomllib.load(fh)), [])

    def test_a_size_that_does_not_convert_to_grams_is_refused(self):
        for book in ({"package": [{"food": "Salt", "sizes": [[1, "cup"]]}]},
                     {"package": [{"food": "Flour2", "sizes": [[1, "lb"]]}]}):
            with self.subTest(book=book), self.assertRaises(ProfileError):
                instance(book)


class Levels(unittest.TestCase):
    def test_the_public_level_states_each_size_as_estimated(self):
        g = instance()
        self.assertEqual(sizes(g, PUBLIC_LEVEL, "Flour"), [("2 lb bag", 2.0, "lb"), ("5 lb bag", 5.0, "lb")])
        (dozen,) = food_packages(g, package_table(g, PUBLIC_LEVEL), "Egg")
        self.assertEqual(dozen, Package(12.0, "each", "dozen", PUBLIC_LEVEL, True))
        spec = g.nodes[f"DefaultSpecification:{PUBLIC_LEVEL} -- Milk -- gallon"]
        self.assertEqual(spec["provenance"], "estimated")
        self.assertIn("128 fl_oz = 3898.97", spec["source"])

    def test_a_food_takes_its_parents_sizes(self):
        self.assertEqual(sizes(instance(), PUBLIC_LEVEL, "Butter (salted)"), [("1 lb", 1.0, "lb")])
        self.assertEqual(sizes(instance(), PUBLIC_LEVEL, "Salt"), [])

    def test_the_owners_sizes_replace_a_foods_and_the_rest_fall_back(self):
        g = instance()
        report = home(g)
        self.assertEqual(report.written, [f"{HOME_LEVEL} -- Flour -- 1 kg bag"])
        self.assertEqual(sizes(g, HOME_LEVEL, "Flour"), [("1 kg bag", 1.0, "kg")])
        self.assertEqual(sizes(g, HOME_LEVEL, "Milk"), [("gallon", 128.0, "fl_oz")])
        (bag,) = food_packages(g, package_table(g, HOME_LEVEL), "Flour")
        self.assertFalse(bag.estimated)
        self.assertEqual(default_level(g), HOME_LEVEL)

    def test_again_changes_nothing_and_a_dropped_size_is_removed(self):
        g = instance()
        self.assertEqual(import_packages(g, parse_packages(BOOK))["created"], 0)
        import_packages(g, parse_packages({"package": [{"food": "Flour", "sizes": [[5, "lb", "5 lb bag"]]}] + BOOK["package"][1:]}))
        self.assertEqual(sizes(g, PUBLIC_LEVEL, "Flour"), [("5 lb bag", 5.0, "lb")])
        self.assertNotIn(f"QuantitySpecification:{PUBLIC_LEVEL} -- Flour -- 2 lb bag size", g.nodes)
        home(g)
        self.assertEqual(home(g, own={}).removed, [f"{HOME_LEVEL} -- Flour -- 1 kg bag"])
        self.assertEqual(sizes(g, HOME_LEVEL, "Flour"), [("5 lb bag", 5.0, "lb")])

    def test_what_cannot_be_instantiated_is_refused(self):
        for selection in ({"name": HOME_LEVEL, "profile": "Nowhere"}, {"name": PUBLIC_LEVEL},
                          {"name": HOME_LEVEL, "own": {"Flour2": {"sizes": [[1, "lb"]]}}},
                          {"name": HOME_LEVEL, "own": {"Salt": {"sizes": [[1, "cup"]]}}},
                          {"name": HOME_LEVEL, "own": {"Flour": {"sizes": [[1, "lb"]], "price": 3}}}):
            with self.subTest(selection=selection), self.assertRaises(ProfileError):
                instantiate_packages(instance(), selection)

    def test_no_level_loaded(self):
        g = WritableGraph()
        self.assertIsNone(default_level(g))
        with self.assertRaises(ProfileError):
            package_table(g, PUBLIC_LEVEL)


def shelf(g, food, days, *keys):
    name = f"{food} shelf life {' '.join(keys)}"
    g.add("QuantitySpecification", f"{name} value", value=days, unit="days")
    g.add("DefaultSpecification", name, name, hasKind=Ref("ShelfLife"), keyedBy=[Ref(k) for k in keys],
          hasValue=Ref(f"{name} value"))
    g.nodes[food]["defaultSpecifications"].append(Ref(name))


def sold_in(**sizes):
    return {food: tuple(Package(grams, "g", label, "US", True) for label, grams in s) for food, s in sizes.items()}


def week_with_shelf_lives():
    g = week()
    for name in ("ShelfLife", "Fridge", "Pantry", "Freezer", "Opened", "Sealed"):
        g.add("DomainType", name, name, defaultSpecifications=[])
    shelf(g, "Eggs", 21, "Fridge")
    shelf(g, "Eggs", 3, "Fridge", "Opened")
    shelf(g, "Noodles", 730, "Pantry")
    return g


PACKAGES = sold_in(Eggs=[("half box", 300.0), ("box", 600.0)], Noodles=[("12 oz bag", 340.0)])


class TheListRoundedUp(unittest.TestCase):
    def test_whole_packages_what_is_left_and_what_it_costs(self):
        shopping = shopping_list(week_with_shelf_lives(), "week", NOW, priced(Eggs=0.5, Noodles=0.3), PACKAGES)
        lines = {line.food: line for line in shopping.to_buy}
        eggs, noodles = lines["Eggs"], lines["Noodles"]
        self.assertEqual((eggs.buy, eggs.packages, eggs.bought, eggs.left), (450.0, [(1, "box")], 600.0, 150.0))
        self.assertEqual((noodles.packages, noodles.bought, noodles.left), ([(1, "12 oz bag")], 340.0, 140.0))
        self.assertAlmostEqual(eggs.cost, 3.00)
        self.assertAlmostEqual(eggs.left_cost, 0.75)
        self.assertAlmostEqual(noodles.cost, 1.02)
        self.assertAlmostEqual(noodles.left_cost, 0.42)
        self.assertAlmostEqual(shopping.total, 4.02)
        self.assertAlmostEqual(shopping.left_total, 1.17)
        self.assertTrue(eggs.estimated_size)

    def test_what_is_left_keeps_from_its_first_use_once_opened_or_unopened(self):
        lines = {line.food: line for line in shopping_list(week_with_shelf_lives(), "week", NOW, None, PACKAGES).to_buy}
        self.assertEqual((lines["Eggs"].keeps_until, lines["Eggs"].keeps_opened), (when(28, 18) + timedelta(days=3), True))
        self.assertEqual((lines["Noodles"].keeps_until, lines["Noodles"].keeps_opened), (when(29, 18) + timedelta(days=730), False))

    def test_an_unopened_figure_in_the_pantry_is_not_how_long_an_opened_one_keeps(self):
        g = week_with_shelf_lives()
        shelf(g, "Noodles", 5, "Fridge", "Opened")             # as an opened can: days in the fridge, not years
        lines = {line.food: line for line in shopping_list(g, "week", NOW, None, PACKAGES).to_buy}
        self.assertEqual((lines["Noodles"].keeps_until, lines["Noodles"].keeps_opened), (when(29, 18) + timedelta(days=5), True))

    def test_no_shelf_life_known_and_nothing_left_over(self):
        g = week()
        lines = {line.food: line for line in shopping_list(g, "week", NOW, None, sold_in(Eggs=[("pack", 450.0)])).to_buy}
        self.assertEqual((lines["Eggs"].left, lines["Eggs"].keeps_until), (0.0, None))
        self.assertEqual((lines["Noodles"].packages, lines["Noodles"].bought, lines["Noodles"].left), ([], 200.0, 0.0))

    def test_without_a_package_level_it_buys_what_is_needed(self):
        lines = {line.food: line for line in shopping_list(week(), "week", NOW, priced(Eggs=0.5)).to_buy}
        self.assertEqual((lines["Eggs"].packages, lines["Eggs"].bought, lines["Eggs"].left), ([], 450.0, 0.0))
        self.assertAlmostEqual(lines["Eggs"].cost, 2.25)

    def test_a_counted_food_with_no_size_is_bought_in_whole_items(self):
        line = Line("Tortilla", 130.0, 130.0, 0.0, each=50.0)
        _round_up(None, line, "Tortilla", None)
        self.assertEqual((line.bought, line.left), (150.0, 20.0))
        self.assertEqual(line.amount(), "3 (about 150 g)")


class InWords(unittest.TestCase):
    def test_packages_and_what_is_left(self):
        shopping = shopping_list(week_with_shelf_lives(), "week", NOW, priced(Eggs=0.5, Noodles=0.3), PACKAGES)
        text = describe(shopping, timezone.utc, "Home prices", "US")
        self.assertIn("rounded up to what is sold, at 'US'", text)
        self.assertIn("1 x box (about 600 g)+", text)
        self.assertIn("150 g (5.3 oz) left over ($0.75); keeps to Thu 01 Oct 2026 once opened", text)
        self.assertIn("140 g (4.9 oz) left over ($0.42); keeps to Thu 28 Sep 2028 unopened", text)
        self.assertIn("About $4.02 at 'Home prices', of which $1.17 is left over", text)

    def test_without_a_package_level_it_says_so(self):
        text = describe(shopping_list(week(), "week", NOW), timezone.utc)
        self.assertIn("amounts are what the recipes use, not package sizes", text)
        self.assertNotIn("left over", text)


if __name__ == "__main__":
    unittest.main()
