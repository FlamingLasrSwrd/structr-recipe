"""Prices (mealplanner/prices.py, tools/price_extract.py): the levels, resolution, the owner's own, and cost.

Worked out by hand. CPI 300 over a 2017-18 mean of 250 brings a Purchase to Plate price forward x1.2.
  Flour  Purchase to Plate $0.10/100 g -> $0.12; BLS U.S. $0.548 a lb (453.592 g) -> $0.120813/100 g
  Egg    BLS U.S. $2.272 a dozen of 50 g eggs (600 g) -> $0.378667; West $2.50 -> $0.416667
  Milk   BLS West $4.831 a gallon, 128 fl oz x 29.5735 mL x 1.03 g/mL = 3898.970 g -> $0.123905 (a proxy)
  Oil    Purchase to Plate $0.50, cooked -> $0.60, estimated; the owner's $10 a litre, 920 g -> $1.086957
  Butter (salted) has no price of its own: its parent Butter's, $0.90 -> $1.08
A recipe from "Home" (below West): flour 200 g, 2 eggs (100 g), 1 cup of milk (236.588 mL -> 243.68564 g),
salt 5 g (no price), 100 g of water (free, and not named as an estimate), and an optional 14 g of
butter (left out), for 4 servings:
  200 x 0.120813 + 100 x 0.416667 + 243.68564 x 0.123905 = 24.1627 + 41.6667 + 30.1938 cents
  = $0.960232 -> $0.240058 a serving
"""

import unittest
from types import SimpleNamespace

from mealplanner.prices import (
    PPNAP_LEVEL, US_LEVEL, WEST_LEVEL, describe_cost, food_price, import_prices, instantiate_prices, parse_prices,
    price_table, recipe_cost,
)
from mealplanner.profiles import ProfileError
from tests.fakegraph import Ref, WritableGraph
from tools.price_extract import pin_bls

BOOK = {
    "bls": {"701111": {"name": "Flour", "per": [1, "lb"]}, "708111": {"name": "Eggs", "per": [12, "each"]},
            "709112": {"name": "Milk", "per": [128, "fl_oz"]}},
    "price": [{"food": "Flour", "bls": "701111", "ppnap": 1}, {"food": "Egg", "bls": "708111"},
              {"food": "Milk", "bls": "709112", "proxy": True}, {"food": "Oil", "ppnap": 2, "cooked": True},
              {"food": "Butter", "ppnap": 3}, {"food": "Water", "free": True}],
}
BLS = {"cpi": {"series": "CPI", "base": {"period": "2017-2018 mean", "value": 250.0}, "latest": {"period": "2026-08", "value": 300.0}},
       "items": {"701111": {"US": {"period": "2026-08", "value": 0.548}},
                 "708111": {"US": {"period": "2026-08", "value": 2.272}, "West": {"period": "2026-08", "value": 2.5}},
                 "709112": {"US": {"period": "2026-08", "value": 4.229}, "West": {"period": "2026-07", "value": 4.831}}}}
PPNAP = {"year": "2017/2018", "foods": {"1": {"description": "Flour", "price_100g": 0.1},
                                        "2": {"description": "Oil", "price_100g": 0.5},
                                        "3": {"description": "Butter", "price_100g": 0.9}}}


def instance():
    g = WritableGraph()
    for h in ("Default Kind", "Food Identity"):
        g.add("TypeHierarchy", h, h)
    for kind in ("Density", "MassPerUnit"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Default Kind"), defaultSpecifications=[])
    for food in ("Flour", "Egg", "Milk", "Oil", "Butter", "Water", "Salt"):
        g.add("DomainType", food, food, hierarchy=Ref("Food Identity"), defaultSpecifications=[])
    g.add("DomainType", "Butter (salted)", "Butter (salted)", hierarchy=Ref("Food Identity"), parent=Ref("Butter"),
          defaultSpecifications=[])
    for food, kind, value, unit in (("Milk", "Density", 1.03, "g_per_mL"), ("Oil", "Density", 0.92, "g_per_mL"),
                                    ("Egg", "MassPerUnit", 50.0, "g_per_each")):
        g.add("QuantitySpecification", f"{food} {kind} value", value=value, unit=unit, status="default")
        g.add("DefaultSpecification", f"{food} {kind}", forType=Ref(food), hasKind=Ref(kind), keyedBy=[],
              hasValue=Ref(f"{food} {kind} value"))
        g.nodes[food]["defaultSpecifications"].append(Ref(f"{food} {kind}"))
    import_prices(g, parse_prices(BOOK), BLS, PPNAP)
    return g


def recipe(g):
    """The recipe of the header, and an intermediate its second step makes and uses."""
    specs = []
    for i, (food, value, unit, role, optional) in enumerate((
            ("Flour", 200, "g", "input", False), ("Egg", 2, "each", "input", False), ("Milk", 1, "cup", "input", False),
            ("Salt", 5, "g", "input", False), ("Butter (salted)", 14, "g", "input", True),
            ("Water", 100, "g", "input", False), ("Oil", 50, "g", "output", False), ("Oil", 50, "g", "input", False))):
        g.add("QuantitySpecification", f"q{i}", value=value, unit=unit)
        g.add("Specification", f"s{i}", hasParticipationRole=role, specifies=Ref(food), hasSpecifiedQuantity=Ref(f"q{i}"),
              isOptional=optional)
        specs.append(Ref(f"s{i}"))
    g.add("Step", "step 1", hasSpecification=specs[:7])
    g.add("Step", "step 2", hasSpecification=specs[7:])
    g.add("Plan", "cake", "Cake v1", steps=[Ref("step 1"), Ref("step 2")])
    return g.get_all("Plan", "cake")["result"]


def home(g, own=None):
    return instantiate_prices(g, {"name": "Home", "profile": WEST_LEVEL,
                                  "own": own if own is not None else {"Oil": {"price": 10, "amount": 1, "unit": "l"}}})


def price_of(g, level, food):
    return food_price(g, price_table(g, level), food)


class Definitions(unittest.TestCase):
    def test_every_problem_is_reported(self):
        bad = {"bls": {"1": {"name": "x", "per": [0, "lb"]}},
               "price": [{"food": "A"}, {"food": "B", "bls": "9"}, {"food": "C", "free": True, "ppnap": 4},
                         {"food": "D", "bls": "1", "cooked": True}, {"food": "A", "ppnap": 1}, {"food": "E", "ppnap": 1, "colour": 1}]}
        with self.assertRaises(ProfileError) as caught:
            parse_prices(bad)
        self.assertEqual(len(caught.exception.problems), 8)

    def test_a_price_the_pins_lack_is_refused(self):
        with self.assertRaises(ProfileError):
            import_prices(instance(), parse_prices({**BOOK, "price": [{"food": "Oil", "ppnap": 7}]}), BLS, PPNAP)

    def test_a_food_not_in_the_vocabulary_or_not_countable_in_grams_is_refused(self):
        for price in ({"food": "Flour2", "ppnap": 1}, {"food": "Salt", "bls": "708111"}):
            with self.subTest(price=price), self.assertRaises(ProfileError):
                import_prices(instance(), parse_prices({**BOOK, "price": [price]}), BLS, PPNAP)


class Levels(unittest.TestCase):
    def test_each_level_states_its_own_and_the_nearest_wins(self):
        g = instance()
        self.assertAlmostEqual(price_of(g, PPNAP_LEVEL, "Flour").quantity["value"], 0.12, places=5)
        self.assertAlmostEqual(price_of(g, US_LEVEL, "Flour").quantity["value"], 0.120813, places=5)
        self.assertAlmostEqual(price_of(g, WEST_LEVEL, "Flour").quantity["value"], 0.120813, places=5)   # no West figure
        self.assertAlmostEqual(price_of(g, US_LEVEL, "Egg").quantity["value"], 0.378667, places=5)
        self.assertAlmostEqual(price_of(g, WEST_LEVEL, "Egg").quantity["value"], 0.416667, places=5)
        self.assertAlmostEqual(price_of(g, WEST_LEVEL, "Milk").quantity["value"], 0.123905, places=5)
        self.assertIsNone(price_of(g, PPNAP_LEVEL, "Egg"))

    def test_status_and_source(self):
        g = instance()
        status = {f: price_of(g, WEST_LEVEL, f).spec["provenance"] for f in ("Flour", "Egg", "Milk", "Oil", "Butter", "Water")}
        self.assertEqual(status, {"Flour": "sourced", "Egg": "sourced", "Milk": "estimated", "Oil": "estimated",
                                  "Butter": "calculated", "Water": "estimated"})
        self.assertIn("APU0400708111", price_of(g, WEST_LEVEL, "Egg").spec["source"])
        self.assertIn("x 1.2000", price_of(g, WEST_LEVEL, "Butter").spec["source"])
        self.assertEqual(price_of(g, WEST_LEVEL, "Water").quantity["value"], 0.0)

    def test_a_food_takes_its_parents_price(self):
        self.assertAlmostEqual(price_of(instance(), WEST_LEVEL, "Butter (salted)").quantity["value"], 1.08, places=5)

    def test_again_changes_nothing_and_a_dropped_price_is_removed(self):
        g = instance()
        self.assertEqual(import_prices(g, parse_prices(BOOK), BLS, PPNAP)["created"], 0)
        import_prices(g, parse_prices({**BOOK, "price": BOOK["price"][1:]}), BLS, PPNAP)
        self.assertIsNone(price_of(g, WEST_LEVEL, "Flour"))
        self.assertNotIn(f"QuantitySpecification:{US_LEVEL} -- Flour price", g.nodes)


class OwnersPrices(unittest.TestCase):
    def test_the_owners_price_wins_and_falls_back_to_the_chosen_level(self):
        g = instance()
        home(g)
        oil = price_of(g, "Home", "Oil")
        self.assertAlmostEqual(oil.quantity["value"], 1.086957, places=5)
        self.assertEqual((oil.quantity["status"], oil.spec["provenance"]), ("specified", "sourced"))
        self.assertIn("the owner's price", oil.spec["source"])
        self.assertAlmostEqual(price_of(g, "Home", "Egg").quantity["value"], 0.416667, places=5)

    def test_a_price_the_file_drops_is_removed_and_nothing_else(self):
        g = instance()
        home(g)
        report = home(g, own={})
        self.assertEqual(report.removed, ["Home -- Oil"])
        self.assertAlmostEqual(price_of(g, "Home", "Oil").quantity["value"], 0.6, places=5)

    def test_what_cannot_be_instantiated_is_refused(self):
        for selection in ({"name": "Home", "profile": "Nowhere"}, {"name": WEST_LEVEL, "profile": US_LEVEL},
                          {"name": "Home", "profile": WEST_LEVEL, "own": {"Flour2": {"price": 1, "amount": 1, "unit": "g"}}},
                          {"name": "Home", "profile": WEST_LEVEL, "own": {"Oil": {"price": -1, "amount": 1, "unit": "l"}}},
                          {"name": "Home", "profile": WEST_LEVEL, "own": {"Salt": {"price": 1, "amount": 1, "unit": "cup"}}}):
            with self.subTest(selection=selection), self.assertRaises(ProfileError):
                instantiate_prices(instance(), selection)


class Cost(unittest.TestCase):
    def test_a_recipes_cost_a_serving(self):
        g = instance()
        home(g)
        cost = recipe_cost(g, recipe(g), price_table(g, "Home"), 4.0)
        self.assertAlmostEqual(cost.per_serving, 0.240058, places=5)
        self.assertEqual((cost.unpriced, cost.estimated), (["Salt"], ["Milk"]))

    def test_the_week_costs_its_cooks_and_leftovers_nothing_more(self):
        g = instance()
        home(g)
        plan = recipe(g)
        problem = SimpleNamespace(
            slots=[SimpleNamespace(key=k) for k in ("a", "b", "c")],
            candidates={plan["id"]: SimpleNamespace(id=plan["id"], name="Cake v1", yield_servings=4.0)})
        evaluation = SimpleNamespace(
            # the leftover names its recipe too, as a committed leftover may: its kind alone keeps it from costing again
            picks=[SimpleNamespace(candidate=plan["id"]), SimpleNamespace(candidate=plan["id"]), SimpleNamespace(candidate=plan["id"])],
            slot_details=[{"slot": "a", "kind": "cook", "cooked_servings": 2.0}, {"slot": "b", "kind": "leftover"},
                          {"slot": "c", "kind": "cook", "cooked_servings": 1.0}])
        text = describe_cost(g, problem, evaluation, "Home", 2)
        self.assertIn("about $0.72 for the meals this week cooks, $0.36 a day", text)      # 3 x 0.240058
        self.assertIn("Cake v1: $0.24 a serving (1 ingredient not priced)", text)
        self.assertIn("not priced, so left out: Salt", text)
        self.assertIn("priced from an estimate (a similar food, or a cooked price): Milk", text)


class Pins(unittest.TestCase):
    def test_the_latest_published_month_and_a_west_price_only_within_a_year(self):
        def series(sid, points):
            return {"seriesID": sid, "data": [{"year": y, "period": f"M{m:02d}", "value": v} for y, m, v in points]}
        cpi = [(str(y), m, "100") for y in (2017, 2018) for m in range(1, 13)] + [("2026", 8, "150")]
        answers = {"series": [
            series("CUUR0000SAF11", cpi),
            series("APU0000701111", [("2026", 8, "-"), ("2026", 7, "0.55"), ("2025", 12, "0.50")]),
            series("APU0400701111", [("2025", 6, "0.60")]),
            series("APU0000708111", [("2026", 8, "2.27")]),
            series("APU0400708111", [("2025", 8, "2.40")]),
        ]}
        book = parse_prices({"bls": {"701111": {"name": "Flour", "per": [1, "lb"]}, "708111": {"name": "Eggs", "per": [12, "each"]}},
                             "price": []})
        pin = pin_bls(book, answers)
        self.assertEqual(pin["items"], {"701111": {"US": {"period": "2026-07", "value": 0.55}},
                                        "708111": {"US": {"period": "2026-08", "value": 2.27},
                                                   "West": {"period": "2025-08", "value": 2.4}}})
        self.assertEqual((pin["cpi"]["base"]["value"], pin["cpi"]["latest"]), (100.0, {"period": "2026-08", "value": 150.0}))


if __name__ == "__main__":
    unittest.main()
