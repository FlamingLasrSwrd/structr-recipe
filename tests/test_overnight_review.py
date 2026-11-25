"""The defects the review of 2026-11-22 found (REVIEW.md, "Found by our own audits"), each as a test.

Worked by hand on tests/test_planning_extract.py's kitchen: an omelette (yield 2) takes 300 g of eggs,
and here a second step takes 50 g more of them, so a cook for 2 draws 350 g; pasta (yield 2) takes 200 g
of noodles and 100 g of eggs. Run against 4b1f231, the code these fix, every test here fails but those
named "still" and those of WhatTheSuiteMissed, which hold six changes made to that
code on purpose that its own suite did not notice.
"""

import io
import json
import math
import pathlib
import re
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from mealplanner.fdc_packages import common_sizes, package_ounces
from mealplanner.inventory import assumed_storage
from mealplanner.menu_changes import MenuError, skip
from mealplanner.packages import HOME_LEVEL, PUBLIC_LEVEL, choose, instantiate_packages, parse_packages
from mealplanner.pantry import PantryError, buy, cook, stock_take, use
from mealplanner.planning.commit import commit_plan
from mealplanner.planning.evaluate import evaluate
from mealplanner.planning.model import Candidate, Fixed, Pick, PlanningProblem, Slot, Weights
from mealplanner.prices import PRICE_HIERARCHY, instantiate_prices
from mealplanner.products import Product, ProductError, import_products, parse_products
from mealplanner.profiles import ProfileError
from mealplanner.shopping import left_over_keeps, shopping_list
from mealplanner.vocabulary_import import nutrient_name
from structr_client.client import StructrError
from tests import test_menu_changes, test_packages, test_products, test_shopping
from tests.fakegraph import Ref, WritableGraph, at, when
from tests.planning_graph import add_entry, add_portion, add_type
from tests.test_pantry import NOW, grams, pantry, portion_named
from tools import check_pages, instantiate_profile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def eggs_twice():
    """The kitchen, the omelette taking 50 g more of eggs in a second specification."""
    g = pantry()
    g.add("QuantitySpecification", "more eggs q", value=50.0, unit="g")
    g.add("Specification", "more eggs", hasParticipationRole="input", specifies=Ref("Eggs"), isOptional=False,
          hasSpecifiedQuantity=Ref("more eggs q"))
    g.nodes["step omelette"]["hasSpecification"].append(Ref("more eggs"))
    return g


class ACookDrawsEveryUse(unittest.TestCase):
    def test_a_food_used_twice_is_drawn_twice_from_one_portion(self):
        g = eggs_twice()
        buy(g, "Eggs", 600, "g", when(25, 8), "t1")
        add_entry(g, "e1", "omelette", at(25, 9), servings=2.0)
        booking, short = cook(g, "e1", when(25, 10), "c1")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        self.assertEqual((grams(g, eggs, when(25, 11)), short), (250.0, []))       # 600 - 300 - 50
        drawn = sorted(n["name"] for n in g.nodes.values() if n["type"] == "Allocation")
        first = f"{booking.process} -- Eggs from Purchase t1 -- Eggs"
        self.assertEqual(drawn, [first, first + " #2"])

    def test_the_second_use_gets_only_what_the_first_left(self):
        g = eggs_twice()
        buy(g, "Eggs", 320, "g", when(25, 8), "t1")
        add_entry(g, "e1", "omelette", at(25, 9), servings=2.0)
        _, short = cook(g, "e1", when(25, 10), "c1")
        self.assertEqual(grams(g, portion_named(g, "Purchase t1 -- Eggs"), when(25, 11)), 0.0)
        self.assertEqual([(s.food, s.needed, s.drawn) for s in short], [("Eggs", 50.0, 20.0)])

    def test_a_whole_item_in_stock_is_drawn(self):
        g = pantry()
        g.get_all = strict(g.get_all)
        add_portion(g, "whole eggs", "Eggs", 400.0, at(25, 8))
        g.nodes["whole eggs"]["type"] = "DiscreteWholeItem"
        add_entry(g, "e1", "omelette", at(25, 9), servings=2.0)
        _, short = cook(g, "e1", when(25, 10), "c1")
        self.assertEqual(short, [])


def strict(get_all):
    """get_all as Structr answers it: a node asked for as another type is not found."""
    def read(type_name, node_id=None, **kwargs):
        found = get_all(type_name, node_id, **kwargs)
        if node_id is not None and type_name == "PortionOfSubstance" and found["result"]["type"] != type_name:
            raise StructrError("GET", f"/structr/rest/{type_name}/{node_id}", 404, {"code": 404})
        return found
    return read


class AmountsAreNumbers(unittest.TestCase):
    def test_nan_and_infinity_are_refused_before_anything_is_written(self):
        g = pantry()
        buy(g, "Eggs", 600, "g", NOW, "t1")
        eggs = portion_named(g, "Purchase t1 -- Eggs")
        posts = g.posts
        for bad in (math.nan, math.inf):
            for book in (lambda: buy(g, "Eggs", bad, "g", NOW, "t2"), lambda: use(g, eggs, bad, "g", when(26, 8), "u1"),
                         lambda: stock_take(g, eggs, bad, "g", when(26, 8), "s1")):
                with self.assertRaises(PantryError):
                    book()
        self.assertEqual(g.posts, posts)

    def test_so_are_a_products_and_a_packages_size(self):
        row = {"name": "Farm eggs dozen", "food": "Eggs", "barcodes": ["036000291452"], "amount": math.inf, "unit": "g"}
        with self.assertRaises(ProductError):
            parse_products({"product": [row]})
        with self.assertRaises(ProfileError):
            parse_packages({"package": [{"food": "Flour", "sizes": [[math.nan, "g"]]}]})


class AMealWrittenAgain(unittest.TestCase):
    """An entry is named by its meal and recipe, so a skipped meal planned again is the same node."""

    def setUp(self):
        self.g = WritableGraph()
        self.g.upsert = self.upsert
        self.g.add("MealPlan", "wk", "Week of 2026-09-28", hasEntry=[])
        self.g.add("MealPlan", "other", "Week of 2026-09-29", hasEntry=[])
        self.g.add("Plan", "soup", "Soup v1")
        self.soup = Candidate(id="soup", name="Soup v1", meal_types=frozenset(), minutes=30, difficulty=None, nutrients={},
                              untrusted=frozenset(), leftover_days=3, hard_excluded=False, soft_penalty=0.0, recipe=None,
                              ahead_hours=0.0)
        self.monday, self.tuesday = Slot("Mon Dinner", when(28, 18), None), Slot("Tue Dinner", when(29, 18), None)

    def upsert(self, type_name, key, value, fields):
        for node in self.g.nodes.values():
            if node["type"] == type_name and node["name"] == value:
                self.g.patch(f"/{type_name}/{node['id']}", fields)
                return node["id"]
        return self.g.post(f"/{type_name}", {"name": value, **fields})["result"][0]

    def commit(self, slots, picks, week="wk"):
        p = PlanningProblem(slots=tuple(slots), candidates={"soup": self.soup}, targets=(), weights=Weights(), now=when(27))
        return commit_plan(self.g, week, p, evaluate(p, picks))

    def test_a_skipped_cook_replanned_as_leftovers_is_only_leftovers(self):
        monday, tuesday = self.commit([self.monday, self.tuesday], [Pick(candidate="soup"), Pick(candidate="soup")])
        self.g.patch(f"/MealPlanEntry/{tuesday}", {"isSkipped": True})
        name = self.g.nodes[monday]["name"]
        kept = Slot(name, when(28, 18), None,
                    Fixed(eaten=1.0, candidate="soup", cooked=1.0, name=name, entry_id=monday, shares=()))
        self.assertEqual(self.commit([kept, self.tuesday], [Pick(candidate="soup"), Pick(source=0)]), [tuesday])
        entry = self.g.nodes[tuesday]
        self.assertEqual((entry.get("references"), entry.get("hasPlannedServings"), entry["isSkipped"]), (None, None, False))
        self.assertEqual(entry["consumesLeftoverFrom"].id, monday)

    def test_another_weeks_meal_is_not_taken(self):
        self.commit([self.monday], [Pick(candidate="soup")])
        posts, patches = self.g.posts, self.g.patches
        with self.assertRaises(ValueError) as caught:       # OtherWeeksMealError, which tools/plan_week.py prints
            self.commit([self.monday], [Pick(candidate="soup")], week="other")
        self.assertIn("Week of 2026-09-28", str(caught.exception))
        self.assertEqual((self.g.posts, self.g.patches), (posts, patches))

    def test_skipping_back_to_a_leftover_meals_recipe_makes_it_a_cook(self):
        g = test_menu_changes.week()
        lunch = test_menu_changes.LUNCH
        skip(g, lunch, "Tacos")
        skip(g, "MealPlanEntry:Tue 27 Oct Lunch -- Tacos v2", "Soup")
        entry = g.nodes[lunch]
        self.assertEqual((entry["references"].id, entry.get("consumesLeftoverFrom"), entry["hasPlannedServings"]),
                         ("Soup v1", None, 1.0))

    def test_a_replacement_does_not_take_another_weeks_meal(self):
        g = test_menu_changes.week()
        g.add("MealPlan", "other", "Week of 2026-10-25", hasEntry=[])
        g.post("/MealPlanEntry", {"name": "Mon 26 Oct Dinner -- Tacos v2", "memberOf": "other", "isSkipped": False})
        with self.assertRaises(MenuError):
            skip(g, test_menu_changes.DINNER, "Tacos")
        self.assertEqual(g.nodes["MealPlanEntry:Mon 26 Oct Dinner -- Tacos v2"]["memberOf"].id, "other")


class TheShoppingList(unittest.TestCase):
    def test_a_shortfall_of_rounding_is_no_purchase(self):
        listed = shopping_list(test_shopping.week(eggs_on_hand=700.0 - 4e-7), "week", test_shopping.NOW)
        self.assertEqual([line.food for line in listed.to_buy], ["Noodles"])
        self.assertEqual([(line.food, line.buy) for line in listed.covered], [("Eggs", 0.0)])

    def test_a_shortfall_of_a_hundredth_of_a_gram_still_is_one(self):
        listed = shopping_list(test_shopping.week(eggs_on_hand=699.99), "week", test_shopping.NOW)
        self.assertEqual([line.food for line in listed.to_buy], ["Eggs", "Noodles"])


class TheLoaders(unittest.TestCase):
    def test_one_bracket_for_two_is_not_no_products(self):
        with self.assertRaises(ProductError) as caught:
            parse_products({"product": {"name": "Farm eggs dozen"}})
        self.assertIn("[[product]]", str(caught.exception))

    def test_a_misspelt_package_table_is_not_an_empty_file(self):
        for data in ({}, {"packages": [{"food": "Flour", "sizes": [[1, "lb"]]}]}):
            with self.assertRaises(ProfileError):
                parse_packages(data)

    def test_a_misspelt_own_removes_nothing(self):
        g = test_packages.instance()
        test_packages.home(g)
        before = sorted(g.nodes)
        with self.assertRaises(ProfileError) as caught:
            instantiate_packages(g, {"name": HOME_LEVEL, "profile": PUBLIC_LEVEL, "owns": {}})
        self.assertIn("owns", str(caught.exception))
        self.assertEqual(sorted(g.nodes), before)

    def test_a_level_named_as_a_food_leaves_the_food_alone(self):
        g = test_packages.instance()
        with self.assertRaises(ProfileError):
            instantiate_packages(g, {"name": "Flour", "profile": PUBLIC_LEVEL})
        self.assertEqual(g.nodes["Flour"]["hierarchy"].id, "Food Identity")

    def test_a_level_does_not_fall_back_on_itself(self):
        g = test_packages.instance()
        test_packages.home(g)
        with self.assertRaises(ProfileError):
            instantiate_packages(g, {"name": HOME_LEVEL, "profile": HOME_LEVEL})

    def test_the_prices_file_is_held_to_the_same(self):
        g = test_packages.instance()
        g.add("TypeHierarchy", PRICE_HIERARCHY, PRICE_HIERARCHY)
        g.add("DomainType", "Unit Price", "Unit Price", hierarchy=Ref("Default Kind"), defaultSpecifications=[])
        g.add("DomainType", "Public prices", "Public prices", hierarchy=Ref(PRICE_HIERARCHY), defaultSpecifications=[])
        for selection in ({"name": "Flour"}, {"name": "Home prices", "owns": {}}):
            with self.assertRaises(ProfileError):
                instantiate_prices(g, {"profile": "Public prices", **selection})
        self.assertEqual(g.nodes["Flour"]["hierarchy"].id, "Food Identity")

    def test_a_fraction_on_a_label(self):
        for text, ounces in (("1/2 gal", 64.0), ("1 1/2 lb", 24.0), ("3/4 lb/340 g", 12.0), ("454 g/1/2 lb", 8.0)):
            self.assertEqual(package_ounces(text), ounces, text)

    def test_a_slash_between_figures_still_separates_them(self):
        for text, ounces in (("15 oz/425 g", 15.0), ("16 oz/1 lb/454 g", 16.0), ("454 g/1 lb", 16.0)):
            self.assertEqual(package_ounces(text), ounces, text)


class AProduct(unittest.TestCase):
    def test_it_is_assumed_kept_where_its_food_is(self):
        g = WritableGraph()
        for name in ("ShelfLife", "Pantry", "Sealed", "Flour"):
            add_type(g, name)
        add_type(g, "Brand X flour", "Flour")
        g.add("QuantitySpecification", "flour days", value=180.0, unit="days")
        g.add("DefaultSpecification", "flour keeps", hasKind=Ref("ShelfLife"), keyedBy=[Ref("Pantry"), Ref("Sealed")],
              hasValue=Ref("flour days"))
        g.nodes["Flour"]["defaultSpecifications"].append(Ref("flour keeps"))
        self.assertEqual(assumed_storage(g, {"instanceOf": {"id": "Brand X flour"}}), "Pantry")

    def test_its_food_is_still_one_to_choose_in_the_list(self):
        g = test_products.kitchen()
        import_products(g, [Product("Farm eggs dozen", "Eggs", ("00036000291452",), 12.0, "each")])
        said = io.StringIO()
        with redirect_stdout(said):
            instantiate_profile.list_types(g, "pantry", None)
        self.assertTrue(any(re.fullmatch(r"\s+\[ \] Eggs", line) for line in said.getvalue().splitlines()), said.getvalue())


class TheCheckOfThePages(unittest.TestCase):
    def test_the_order_of_the_recipes_without_an_amount_is_no_difference(self):
        want = SimpleNamespace(to_buy=[], covered=[], unquantified={"Salt": ["Soup", "Stew"]}, not_bought=[])
        shown = {"to_buy": [], "covered": [], "unquantified": {"Salt": ["Stew", "Soup"]}, "not_bought": []}
        problems = []
        with mock.patch.multiple(check_pages, shopping_list=mock.Mock(return_value=want),
                                 default_level=mock.Mock(return_value=None), price_table=mock.Mock(return_value=None)):
            check_pages.check_shopping(None, {"id": "w", "name": "the week"}, problems, shown)
        self.assertEqual(problems, [])


class WhatTheSuiteMissed(unittest.TestCase):
    def test_the_first_size_alone_can_be_the_best(self):
        self.assertEqual(choose([800.0, 400.0], 800.0), (1, 0))                # one 800, not two 400s

    def test_a_size_under_ten_percent_is_not_common_whatever_its_owners(self):
        count = {"products": 100, "owners": 20, "sizes": [[15, 91, 18], [29, 9, 9]]}
        self.assertEqual([size for size, *_ in common_sizes(count)], [15])

    def test_a_product_below_another_of_the_same_file_is_refused(self):
        listed = [Product("Farm eggs dozen", "Eggs", ("00036000291452",), 12.0, "each"),
                  Product("Farm eggs half", "Farm eggs dozen", ("00042100005264",), 6.0, "each")]
        g = test_products.kitchen()
        add_type(g, "Farm eggs dozen")                                          # there already, a product of an earlier run
        g.nodes["Farm eggs dozen"]["hierarchy"] = Ref("Food Identity")
        with self.assertRaises(ProductError) as caught:
            import_products(g, listed)
        self.assertIn("is a product, not a food", str(caught.exception))

    def test_what_is_left_keeps_as_long_as_the_longest_opened_figure(self):
        g = WritableGraph()
        for name in ("ShelfLife", "Opened", "Sealed", "Fridge", "Pantry", "Oil"):
            add_type(g, name)
        for storage, days in (("Fridge", 10.0), ("Pantry", 60.0)):
            g.add("QuantitySpecification", f"oil {storage} days", value=days, unit="days")
            g.add("DefaultSpecification", f"oil {storage}", hasKind=Ref("ShelfLife"), keyedBy=[Ref(storage), Ref("Opened")],
                  hasValue=Ref(f"oil {storage} days"))
            g.nodes["Oil"]["defaultSpecifications"].append(Ref(f"oil {storage}"))
        self.assertEqual(left_over_keeps(g, "Oil", when(1)), (when(1) + timedelta(days=60), True))

    def test_a_line_is_optional_only_if_every_use_is(self):
        g = test_shopping.week()
        pasta = next(g.nodes[r.id] for r in g.nodes["step pasta"]["hasSpecification"]
                     if getattr(g.nodes[r.id].get("specifies"), "id", None) == "Eggs")
        pasta["isOptional"] = True
        (eggs,) = [line for line in shopping_list(g, "week", test_shopping.NOW).to_buy if line.food == "Eggs"]
        self.assertFalse(eggs.optional)

    def test_the_leftovers_of_leftovers_are_skipped_too(self):
        g = test_menu_changes.week()
        g.post("/TemporalRegion", {"name": "wed region", "hasBeginning": "2026-10-28T18:30:00+0000"})
        g.post("/MealPlanEntry", {"name": "Wed 28 Oct Lunch -- Soup v1", "memberOf": "wk", "isSkipped": False,
                                  "consumesLeftoverFrom": test_menu_changes.LUNCH, "isAbout": "TemporalRegion:wed region"})
        self.assertEqual(len(skip(g, test_menu_changes.DINNER).skipped), 3)


class ThePagesText(unittest.TestCase):
    """What can be held without a JavaScript engine; tools/check_pages.py and check_bookings.py run them."""

    def test_the_recipe_books_columns_are_nutrients_the_vocabulary_makes(self):
        shown = json.loads(re.search(r"const SHOWN = (\[.*?\]);", (ROOT / "pages" / "recipes.js").read_text()).group(1))
        data = json.loads((ROOT / "data" / "fdc" / "foundation.json").read_text())
        made = {nutrient_name(n["name"]) for n in data["nutrients"].values()}
        self.assertEqual([name for name in shown if name not in made], [])

    def test_no_text_is_pasted_into_a_confirmation_between_quotes(self):
        for path in sorted((ROOT / "pages").rglob("*.js")):
            self.assertNotIn("confirm('", path.read_text(), f"{path.name}: an apostrophe ends it, and the form submits unasked")


if __name__ == "__main__":
    unittest.main()
