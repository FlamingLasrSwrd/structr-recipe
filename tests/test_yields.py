"""Purchased-form yields (mealplanner/yields.py, data-model.md J41): a food's trim, a food bought as another,
how the vocabulary loads them, and what the shopping list buys with them (mealplanner/shopping.py).

Worked out by hand.
  The vocabulary's yields: Lemon juice's FDC record says a lemon yields 48 g, and Lemon weighs 58 g
  an item, so a gram of lemon gives 48 / 58 = 0.827586 g of juice (calculated). Egg white's record
  weighs a large one 33 g, Egg's large one 50 g: 0.66. A trim of 10% refuse is a factor of 0.9.
  The week: a salad for its 2 servings (scale 1) takes 270 g of Onion and 60 g of Lemon juice. Onion's
  trim is 0.9; a gram of Lemon gives 0.8 g of Lemon juice by Juicing; a lemon weighs 58 g. The pantry
  holds 10 g of lemon juice and one lemon (58 g).
  - Lemon juice: 60 - 10 = 50 g short, bought as lemons: 50 / 0.8 = 62.5 g of lemon, less the 58 g on
    hand is 4.5 g: one whole lemon (58 g), 53.5 g of it left. Its line needs 62.5 g and has 58 g.
  - Onion, loose: 270 g as a recipe weighs it is 270 / 0.9 = 300 g as bought. In a 1 lb bag
    (453.592 g as bought, 453.592 x 0.9 = 408.2328 g used): one bag, 138.2328 g left over; at $0.50
    per 100 g, $2.041164 bought and $0.691164 left.
  - Sold in an 8 oz bottle of its own (226.796 g), Lemon juice is bought as itself: one bottle, 176.796 g
    left, and no lemon is on the list. With 60 g of juice on hand it is covered, and no lemon either.
"""

import json
import unittest
from datetime import timezone

from mealplanner.packages import Package
from mealplanner.shopping import Line, describe, shopping_list
from mealplanner.vocabulary_import import VocabularyError, import_vocabulary, parse_vocabulary, yield_figure
from mealplanner.yields import edible_fraction, made_from, ndb_numbers, parse_food_des, sr28_pin
from tests.fakegraph import Ref, at, when
from tests.planning_graph import add_entry, add_portion, add_recipe, add_type, new_kitchen
from tests.test_signed_out import ENGINE, javascript
from tests.test_vocabulary import fdc_subset, instance, vocabulary_data

NOW = when(25, 0)


def add_default(g, name, on, kind, value, unit, keys=(), target=None, source=""):
    g.add("QuantitySpecification", f"{name} value", value=value, unit=unit, status="default")
    fields = dict(forType=Ref(on), hasKind=Ref(kind), keyedBy=[Ref(k) for k in keys], hasValue=Ref(f"{name} value"),
                  provenance="estimated", source=source)
    if target:
        fields["targetType"] = Ref(target)
        g.nodes[target].setdefault("yieldTargetOf", []).append(Ref(name))
    g.add("DefaultSpecification", name, name, **fields)
    g.nodes[on]["defaultSpecifications"].append(Ref(name))


def salad_week(juice_on_hand=10.0, lemon_on_hand=58.0):
    g = new_kitchen()
    for name in ("Yield", "MassPerUnit", "Trimming", "Juicing", "Onion", "Lemon", "Lemon juice"):
        add_type(g, name)
    add_type(g, "Red onion", parent="Onion")
    add_default(g, "Onion as bought", "Onion", "Yield", 0.9, "ratio", ["Trimming"], target="Onion",
                source="test; 0.9 of the food as bought is what a recipe weighs; cut away: skin and ends")
    add_default(g, "Lemon -- Juicing -- Lemon juice", "Lemon", "Yield", 0.8, "ratio", ["Juicing"], target="Lemon juice")
    add_default(g, "Lemon mass per each", "Lemon", "MassPerUnit", 58.0, "g_per_each")
    add_recipe(g, "salad", output_grams=330, protein_per_100g=1, provenance="sourced", yield_servings=2, minutes=10,
               inputs=[("Onion", 270.0), ("Lemon juice", 60.0)])
    add_entry(g, "e1", "salad", at(28, 18), servings=2.0)
    if juice_on_hand:
        add_portion(g, "juice on hand", "Lemon juice", juice_on_hand)
    if lemon_on_hand:
        add_portion(g, "lemon on hand", "Lemon", lemon_on_hand)
    return g


def sold_in(**sizes):
    """A package table as packages.package_table makes it: food id -> its sizes."""
    return {food: tuple(Package(amount, unit, label, "US supermarket", True) for amount, unit, label in rows)
            for food, rows in sizes.items()}


def priced(**per_100g):
    from types import SimpleNamespace
    return {food: SimpleNamespace(quantity={"value": v}, spec={"provenance": "sourced"}) for food, v in per_100g.items()}


class Reading(unittest.TestCase):
    def test_a_foods_trim_its_childs_and_a_food_with_none(self):
        g = salad_week()
        self.assertEqual(edible_fraction(g, "Onion"), (0.9, "skin and ends"))
        self.assertEqual(edible_fraction(g, "Red onion"), (0.9, "skin and ends"))      # its parent's
        self.assertEqual(edible_fraction(g, "Lemon"), (1.0, ""))

    def test_a_trim_targets_its_own_type_and_is_keyed_by_trimming_alone(self):
        g = salad_week()
        g.nodes["Onion as bought"]["targetType"] = Ref("Lemon")
        self.assertEqual(edible_fraction(g, "Onion"), (1.0, ""))
        g = salad_week()
        g.nodes["Onion as bought"]["keyedBy"] = [Ref("Juicing")]
        self.assertEqual(edible_fraction(g, "Onion"), (1.0, ""))

    def test_what_a_food_is_bought_as(self):
        g = salad_week()
        made = made_from(g, "Lemon juice")
        self.assertEqual((made.source, made.factor, made.method), ("Lemon", 0.8, "Juicing"))
        self.assertIsNone(made_from(g, "Lemon"))
        self.assertIsNone(made_from(g, "Onion"))           # its own trim is no food it is bought as

    def test_of_two_foods_that_yield_one_the_first_by_name(self):
        g = salad_week()
        add_type(g, "Bottled juice")
        add_default(g, "Bottled juice -- Juicing -- Lemon juice", "Bottled juice", "Yield", 1.0, "ratio", ["Juicing"],
                    target="Lemon juice")
        self.assertEqual(made_from(g, "Lemon juice").source, "Bottled juice")


class TheList(unittest.TestCase):
    def lines(self, shopping):
        return {line.food: line for line in shopping.to_buy}

    def test_a_food_another_yields_is_bought_as_that_one_and_its_stock_counts(self):
        shopping = shopping_list(salad_week(), "week", NOW)
        lines = self.lines(shopping)
        self.assertNotIn("Lemon juice", lines)
        lemon = lines["Lemon"]
        self.assertAlmostEqual(lemon.need, 62.5)
        self.assertAlmostEqual(lemon.have, 58.0)
        self.assertAlmostEqual(lemon.buy, 4.5)
        self.assertEqual((lemon.each, lemon.bought, lemon.amount()), (58.0, 58.0, "1 (about 58 g)"))
        self.assertEqual(lemon.pieces, [58.0])                     # one lemon: what ticking it puts in the pantry
        self.assertAlmostEqual(lemon.left, 53.5)
        self.assertEqual(len(lemon.made), 1)
        self.assertEqual(lemon.made[0][0], "Lemon juice")
        self.assertAlmostEqual(lemon.made[0][1], 50.0)
        self.assertEqual((lemon.recipes, lemon.first_needed), (["salad"], when(28, 18)))

    def test_a_trimmed_food_bought_loose_is_bought_as_it_is_sold(self):
        onion = self.lines(shopping_list(salad_week(), "week", NOW))["Onion"]
        self.assertEqual((onion.buy, onion.bought, onion.left, onion.edible, onion.trimmed), (270.0, 270.0, 0.0, 0.9, "skin and ends"))
        self.assertAlmostEqual(onion.as_bought, 300.0)
        self.assertEqual(onion.pieces, [270.0])                    # stocked as a recipe weighs it, not with its skin
        self.assertEqual(onion.amount(), "300 g (0.7 lb) as bought")

    def test_a_package_of_a_trimmed_food_holds_its_edible_part(self):
        shopping = shopping_list(salad_week(), "week", NOW, priced(Onion=0.5), sold_in(Onion=[(1, "lb", "1 lb bag")]))
        onion = self.lines(shopping)["Onion"]
        self.assertEqual(onion.packages, [(1, "1 lb bag")])
        self.assertAlmostEqual(onion.bought, 408.2328)
        self.assertAlmostEqual(onion.as_bought, 453.592)
        self.assertEqual(len(onion.pieces), 1)
        self.assertAlmostEqual(onion.pieces[0], 408.2328)          # the bag's edible part: 453.592 x 0.9
        self.assertAlmostEqual(onion.left, 138.2328)
        self.assertAlmostEqual(onion.cost, 2.041164)
        self.assertAlmostEqual(onion.left_cost, 0.691164)
        self.assertEqual(onion.amount(), "1 x 1 lb bag (about 454 g)")

    def test_a_food_sold_in_a_size_of_its_own_is_bought_as_itself(self):
        shopping = shopping_list(salad_week(), "week", NOW, None, sold_in(**{"Lemon juice": [(8, "oz", "8 oz bottle")]}))
        lines = self.lines(shopping)
        self.assertNotIn("Lemon", lines)
        juice = lines["Lemon juice"]
        self.assertEqual((juice.buy, juice.packages, juice.made), (50.0, [(1, "8 oz bottle")], []))
        self.assertAlmostEqual(juice.left, 176.796)

    def test_what_its_own_stock_covers_is_not_bought_as_anything(self):
        shopping = shopping_list(salad_week(juice_on_hand=60.0), "week", NOW)
        self.assertEqual(sorted(self.lines(shopping)), ["Onion"])
        self.assertEqual([line.food for line in shopping.covered], ["Lemon juice"])

    def test_with_no_lemon_on_hand_the_whole_need_is_bought(self):
        lemon = self.lines(shopping_list(salad_week(lemon_on_hand=0), "week", NOW))["Lemon"]
        self.assertAlmostEqual(lemon.buy, 62.5)
        self.assertEqual((lemon.bought, lemon.amount()), (116.0, "2 (about 116 g)"))     # two lemons

    def test_in_words(self):
        text = describe(shopping_list(salad_week(), "week", NOW), timezone.utc)
        self.assertIn("for Lemon juice (50 g)", text)
        self.assertIn("300 g (0.7 lb) as bought", text)
        self.assertIn("90% of it as bought is used (less skin and ends)", text)
        self.assertEqual(Line("Beef", 680.0, 680.0, 0.0).amount(), "680 g (1.5 lb)")      # no purchased form: as before


class Vocabulary(unittest.TestCase):
    def data(self, **foods):
        data = vocabulary_data()
        data["method"] = data["method"] + [{"name": "Trimming"}, {"name": "Juicing"}]
        for food in data["food"]:
            food.update(foods.get(food["name"], {}))
        return data

    def test_a_trim_and_a_yield_from_a_portion(self):
        subset = fdc_subset()
        subset["foods"]["1"]["portions"].append({"amount": 1.0, "label": "garlic yields", "grams": 1.5})
        v = parse_vocabulary(self.data(Onion={"yield_from": {"food": "Garlic", "method": "Juicing", "portion": "garlic yields"}},
                                       Garlic={"trim": {"refuse": 13, "what": "knob and skin", "source": "an estimate"}}), subset)
        foods = {f.name: f for f in v.foods}
        self.assertEqual((foods["Garlic"].trim.factor, foods["Garlic"].trim.status), (0.87, "estimated"))
        factor, status, source = yield_figure(subset, foods["Onion"], foods)
        self.assertEqual((factor, status), (0.5, "calculated"))       # 1.5 g from a 3 g clove
        self.assertIn("'garlic yields' 1.5 g, over Garlic's weight per item 3 g", source)

    def test_sr28s_figure_replaces_the_estimate_and_none_there_is_no_trim(self):
        pin = {"source": {"release": "SR28"}, "foods": {"2": {"ndb": "11215", "description": "Garlic, raw", "refuse": 12.0,
                                                               "what": "Knob and skin"}}}
        trim = {"trim": {"refuse": 13, "what": "knob and skin", "source": "an estimate"}}
        v = parse_vocabulary(self.data(Garlic=trim), fdc_subset(), trim_table=pin)
        garlic = {f.name: f for f in v.foods}["Garlic"]
        self.assertEqual((garlic.trim.refuse, garlic.trim.status, garlic.trim.what), (12.0, "sourced", "Knob and skin"))
        self.assertIn("NDB 11215", garlic.trim.source)
        pin["foods"]["2"]["refuse"] = 0.0
        v = parse_vocabulary(self.data(Garlic=trim), fdc_subset(), trim_table=pin)
        self.assertIsNone({f.name: f for f in v.foods}["Garlic"].trim)

    def test_every_problem_is_named(self):
        bad = self.data(Garlic={"trim": {"refuse": 100, "what": "all", "source": "x"}},
                        Onion={"yield_from": {"food": "Onion", "method": "Juicing", "factor": 0.5, "source": "x"}},
                        Shallot={"yield_from": {"food": "Garlic", "method": "Boiling", "portion": "nope"}},
                        **{"Kosher salt": {"yield_from": {"food": "Garlic", "method": "Juicing", "factor": 0.5}}})
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(bad, fdc_subset())
        text = "\n".join(caught.exception.problems)
        for expected in ("refuse is a percentage", "'Onion' is not another food", "'Boiling' is not a method",
                         "has no single portion 'nope'", "a stated yield needs its source"):
            self.assertIn(expected, text)

    def test_a_trim_needs_the_method_trimming(self):
        data = vocabulary_data()
        data["food"][1]["trim"] = {"refuse": 13, "what": "knob and skin", "source": "x"}
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(data, fdc_subset())
        self.assertIn("no method 'Trimming'", "\n".join(caught.exception.problems))


class Loading(unittest.TestCase):
    def data(self, **foods):
        return Vocabulary.data(self, **foods)

    def load(self, g, data=None, subset=None):
        return import_vocabulary(g, parse_vocabulary(data or vocabulary_data(), subset or fdc_subset())).counts

    def node(self, g, type_name, name):
        (row,) = [r for r in g.get_all(type_name)["result"] if r["name"] == name]
        return row

    def test_loaded_as_yield_defaults_with_their_targets_and_pruned_when_gone(self):
        g = instance()
        subset = fdc_subset()
        subset["foods"]["1"]["portions"].append({"amount": 1.0, "label": "garlic yields", "grams": 1.5})
        data = self.data(Onion={"yield_from": {"food": "Garlic", "method": "Juicing", "portion": "garlic yields"}},
                         Garlic={"trim": {"refuse": 13, "what": "knob and skin", "source": "an estimate"}})
        self.load(g, data, subset)
        trim = self.node(g, "DefaultSpecification", "Garlic as bought")
        self.assertEqual((trim["forType"]["name"], trim["targetType"]["name"], [k["name"] for k in trim["keyedBy"]],
                          trim["hasKind"]["name"], trim["provenance"]), ("Garlic", "Garlic", ["Trimming"], "Yield", "estimated"))
        self.assertEqual(self.node(g, "QuantitySpecification", "Garlic as bought value")["value"], 0.87)
        juice = self.node(g, "DefaultSpecification", "Garlic -- Juicing -- Onion")
        self.assertEqual((juice["forType"]["name"], juice["targetType"]["name"], juice["provenance"]),
                         ("Garlic", "Onion", "calculated"))
        self.assertEqual(edible_fraction(g, self.node(g, "DomainType", "Garlic")["id"]), (0.87, "knob and skin"))
        made = made_from(g, self.node(g, "DomainType", "Onion")["id"])
        self.assertEqual((made.source_name, made.factor), ("Garlic", 0.5))
        again = self.load(g, data, subset)
        self.assertEqual((again["created"], again["changed"], again["deleted"]), (0, 0, 0))
        self.load(g, self.data(), subset)                     # the file gives neither any more
        names = {r["name"] for r in g.get_all("DefaultSpecification")["result"]}
        self.assertFalse({"Garlic as bought", "Garlic -- Juicing -- Onion"} & names)
        self.assertFalse({"Garlic as bought value", "Garlic -- Juicing -- Onion value"}
                         & {r["name"] for r in g.get_all("QuantitySpecification")["result"]})

    def test_a_yield_a_build_seeded_is_not_the_files_to_remove(self):
        g = instance()
        self.load(g, self.data(Garlic={"trim": {"refuse": 13, "what": "knob and skin", "source": "x"}}))
        garlic = self.node(g, "DomainType", "Garlic")["id"]
        stir = self.node(g, "DomainType", "Stir-Frying")["id"]
        kind = self.node(g, "DomainType", "Yield")["id"]
        g.post("/structr/rest/QuantitySpecification", {"name": "Stir-Frying yield factor for Garlic value", "value": 0.8,
                                                       "unit": "ratio"})
        g.post("/structr/rest/DefaultSpecification", {"name": "Stir-Frying yield factor for Garlic", "forType": garlic,
                                                      "hasKind": kind, "keyedBy": [stir], "targetType": garlic,
                                                      "hasValue": "QuantitySpecification:Stir-Frying yield factor for Garlic value"})
        self.load(g, self.data())
        self.assertIn("Stir-Frying yield factor for Garlic", {r["name"] for r in g.get_all("DefaultSpecification")["result"]})

    def test_no_yield_kind_is_made_for_a_file_with_no_yields(self):
        g = instance()
        self.load(g)
        self.assertFalse([r for r in g.get_all("DomainType")["result"] if r["name"] == "Yield"])


class SR28(unittest.TestCase):
    def test_food_des_and_the_pin(self):
        text = ("~11282~^~1100~^~Onions, raw~^~ONIONS,RAW~^~~^~~^~Y~^~Sprouts, skin, ends~^10^~Allium cepa~^6.25^2.78^8.37^3.84\r\n"
                "~09316~^~0900~^~Strawberries, raw~^~STRAWBERRIES,RAW~^~~^~~^~Y~^~Caps and stems~^6^~Fragaria X ananassa~^6.25^3.36^8.37^3.6\r\n"
                "~19296~^~1900~^~Honey~^~HONEY~^~~^~~^~Y~^~~^0^~~^6.25^3.36^8.37^3.68\r\n")
        des = parse_food_des(text)
        self.assertEqual(des["11282"], {"description": "Onions, raw", "what": "Sprouts, skin, ends", "refuse": 10.0})
        ndb = ndb_numbers('"fdc_id","NDB_number"\n"170000","11282"\n"167762","9316"\n"169640","19296"\n"1","99999"\n')
        pin = sr28_pin(des, ndb, [170000, 167762, 169640, 1])
        self.assertEqual(sorted(pin["foods"]), ["167762", "169640", "170000"])         # NDB 99999 is not in SR28
        self.assertEqual(pin["foods"]["167762"], {"ndb": "09316", "description": "Strawberries, raw", "refuse": 6.0,
                                                  "what": "Caps and stems"})
        self.assertEqual(pin["foods"]["169640"]["refuse"], 0.0)


STANDIN_GRAPH = r"""
// A stand-in graph for shoppingFor: the salad of tests/test_yields.py's foods, sizes and defaults
var N = {};
function sNode(type, name, props) {
  var n = Object.assign({id: name, type: type, name: name, defaultSpecifications: [], children: []}, props || {});
  (N[type] = N[type] || []).push(n); return n;
}
var $ = {me: null, request: {}, find: function (type, f) {
  return (N[type] || []).filter(function (n) { return !f || Object.keys(f).every(function (k) { return n[k] === f[k]; }); }); }};
var YIELD = sNode("DomainType", "Yield"), MPU = sNode("DomainType", "MassPerUnit"), PQ = sNode("DomainType", "PurchaseQuantity");
var TRIM = sNode("DomainType", "Trimming"), JUICE = sNode("DomainType", "Juicing");
var Onion = sNode("DomainType", "Onion"), Lemon = sNode("DomainType", "Lemon"), Juice = sNode("DomainType", "Lemon juice", {yieldTargetOf: []});
function sDef(on, name, kind, value, unit, keys, target, source) {
  var d = sNode("DefaultSpecification", name, {hasKind: kind, keyedBy: keys || [], hasValue: {value: value, unit: unit},
                                               targetType: target || null, forType: on, source: source || ""});
  on.defaultSpecifications.push(d); if (target && target.yieldTargetOf) target.yieldTargetOf.push(d);
}
sDef(Onion, "Onion as bought", YIELD, 0.9, "ratio", [TRIM], Onion, "test; cut away: skin and ends");
sDef(Lemon, "Lemon -- Juicing -- Lemon juice", YIELD, 0.8, "ratio", [JUICE], Juice);
sDef(Lemon, "Lemon mass per each", MPU, 58, "g_per_each");
var US = sNode("DomainType", "US supermarket");
SIZES.forEach(function (s) {
  sDef(US, "US supermarket -- " + s[0] + " -- " + s[3], PQ, s[1], s[2], [N.DomainType.filter(function (t) { return t.name === s[0]; })[0]]);
});
var FIRST = new Date("2026-09-28T18:00:00Z");
"""

# Declared after the page's library, so these stand in for its own: the week's needs and stock, given directly
STANDIN_READS = r"""
function needs(week) {
  return {pools: {"Onion": {food: Onion, need: 270, recipes: ["salad"], first: FIRST, optional: false, counted: false},
                  "Lemon juice": {food: Juice, need: 60, recipes: ["salad"], first: FIRST, optional: false, counted: false}},
          unquantified: {}, cooks: 1, leftovers: 0};
}
function eligibleGrams(food) { return STOCK[food.name] || 0; }
function weekZone() { return "UTC"; }
function leftOverKeeps() { return [null, false]; }
"""


def shopping_in_javascript(sizes, stock):
    from tests.test_pantry_buy_unit import ROOT
    lib = ROOT / "pages" / "lib"
    engine = "\n".join((lib / name).read_text() for name in sorted(p.name for p in lib.glob("*.js")))
    program = (f"var result = (function () {{\nvar SIZES = {json.dumps(sizes)}, STOCK = {json.dumps(stock)};\n"
               + STANDIN_GRAPH + engine + "\n" + STANDIN_READS
               + "\nvar list = shoppingFor({}, 'none', false, SIZES.length ? 'US supermarket' : null);\n"
               "return {buy: list.buy.map(function (l) { return {food: l.food, need: l.need, have: l.have, buy: l.buy, bought: l.bought, "
               "left: l.left, as_bought: l.as_bought, edible: l.edible, trimmed: l.trimmed, made: l.made, packages: l.packages}; }), "
               "covered: list.covered.map(function (l) { return l.food; })}; })();")
    return javascript(program)


@unittest.skipUnless(ENGINE, "no node or gjs")
class ThePageAgrees(unittest.TestCase):
    """The page's list (pages/lib/90_shopping.js) over the same week, worked out above."""

    def by_food(self, result):
        return {line["food"]: line for line in result["buy"]}

    def test_bought_as_lemons_and_onions_bought_loose(self):
        lines = self.by_food(shopping_in_javascript([], {"Lemon juice": 10, "Lemon": 58}))
        self.assertEqual(sorted(lines), ["Lemon", "Onion"])
        lemon, onion = lines["Lemon"], lines["Onion"]
        self.assertAlmostEqual(lemon["need"], 62.5)
        self.assertAlmostEqual(lemon["buy"], 4.5)
        self.assertEqual((lemon["bought"], lemon["made"][0][0]), (58, "Lemon juice"))
        self.assertAlmostEqual(lemon["made"][0][1], 50.0)
        self.assertAlmostEqual(lemon["left"], 53.5)
        self.assertEqual((onion["bought"], onion["edible"], onion["trimmed"]), (270, 0.9, "skin and ends"))
        self.assertAlmostEqual(onion["as_bought"], 300.0)

    def test_a_package_holds_the_edible_part_and_a_size_of_its_own_wins(self):
        lines = self.by_food(shopping_in_javascript([["Onion", 1, "lb", "1 lb bag"], ["Lemon juice", 8, "oz", "8 oz bottle"]],
                                                    {"Lemon juice": 10, "Lemon": 58}))
        self.assertEqual(sorted(lines), ["Lemon juice", "Onion"])
        onion, juice = lines["Onion"], lines["Lemon juice"]
        self.assertAlmostEqual(onion["bought"], 408.2328)
        self.assertAlmostEqual(onion["as_bought"], 453.592)
        self.assertAlmostEqual(onion["left"], 138.2328)
        self.assertEqual((juice["buy"], juice["packages"], juice["made"]), (50, [{"count": 1, "label": "8 oz bottle"}], []))

    def test_what_its_own_stock_covers_is_not_bought_as_anything(self):
        result = shopping_in_javascript([], {"Lemon juice": 60, "Lemon": 58})
        self.assertEqual((sorted(self.by_food(result)), result["covered"]), (["Onion"], ["Lemon juice"]))


if __name__ == "__main__":
    unittest.main()
