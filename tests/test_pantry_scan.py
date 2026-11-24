"""The pantry page's barcode box and "Add a product" (pages/pantry.js, pages/lib/55_products.js; docs/pantry.md,
"Products and barcodes"). The page runs in node or gjs, where either is installed, over a stand-in graph,
as tests/test_pantry_buy_unit.py runs it; on an instance tools/check_pages.py compares its scans with
products.find, and tools/check_bookings.py what it writes with products.add_product.

The barcodes are those of tests/test_products.py, each check digit worked there by hand: UPC-A 036000291452
(read as GTIN 00036000291452), EAN-13 4006381333931, UPC-E 04252614 (spelled out to 00042100005264). The
foods: Eggs (an egg weighs 50 g), Noodles (no weight per item), and Beans, a group Chickpeas sits under.
Farm eggs dozen, a product of Eggs holding 12 each, has the UPC-A; Dairy milk 1 L would be a unit Buy
offers, and Jar of honey holds 12 "fluid ounces" written as Buy does not offer them (fl oz is Buy's
fl_oz; it is in no unit table, so its grams are unknown and the amount is left as it is).
"""

import json
import random
import re
import unittest

from mealplanner.products import normalize
from tests.test_pantry_buy_unit import page_code
from tests.test_signed_out import ENGINE, javascript

GRAPH = r"""
var N = {}, seq = 0;
var REVERSE = {parent: "children", hierarchy: "domainTypes", identifierScheme: "identifiersInScheme",
               forType: "defaultSpecifications", inScheme: "concepts"};
function link(n) {
  Object.keys(REVERSE).forEach(function (k) { if (n[k] && n[k].id) (n[k][REVERSE[k]] = n[k][REVERSE[k]] || []).push(n); });
}
function node(type, name, props) {
  var n = Object.assign({id: "id" + (++seq), type: type, name: name, defaultSpecifications: [], children: []}, props || {});
  (N[type] = N[type] || []).push(n); link(n); return n;
}
var written = [];
var $ = {request: REQUEST, me: {name: "Jamie"}, current: null, out: "",
  find: function (type, f) { return (N[type] || []).filter(function (n) { return !f || Object.keys(f).every(function (k) { return n[k] === f[k]; }); }); },
  print: function (s) { $.out += s; },
  cypher: function () { return [{n: 1}]; },
  getRequestHeader: function (h) { return h === "Sec-Fetch-Site" ? "same-origin" : null; },   // a form sent from the page
  doPrivileged: function (f) { f(); },
  doInNewTransaction: function (work, failed) { try { work(); } catch (e) { failed(e); } },
  create: function (type, fields) { written.push(type + " " + fields.name); return node(type, fields.name, fields); }};
var food = node("TypeHierarchy", "Food Identity", {domainTypes: []});
var PQ = node("DomainType", "PurchaseQuantity"), MPU = node("DomainType", "MassPerUnit");
function f(name, parent) { return node("DomainType", name, {hierarchy: food, parent: parent || null}); }
var Eggs = f("Eggs"), Noodles = f("Noodles"), Beans = f("Beans"), Chickpeas = f("Chickpeas", Beans), Honey = f("Honey");
Eggs.defaultSpecifications.push(node("DefaultSpecification", "Eggs MassPerUnit", {hasKind: MPU, keyedBy: [], hasValue: {value: 50, unit: "g_per_each"}}));
var scheme = node("ConceptScheme", "Identifier Scheme"), GTIN = node("Concept", "GTIN", {inScheme: scheme});
function product(name, of, value, unit, gtin) {
  var t = f(name, of);
  t.defaultSpecifications.push(node("DefaultSpecification", name + " package size", {hasKind: PQ, keyedBy: [], hasValue: {value: value, unit: unit}}));
  node("Identifier", "GTIN " + gtin, {identifierValue: gtin, identifierScheme: GTIN, denotesType: t});
}
product("Farm eggs dozen", Eggs, 12, "each", "00036000291452");
product("Jar of honey", Honey, 12, "fl oz", "04006381333931");
"""


def page(**request) -> dict:
    """The page drawn for a request: its HTML, what it printed of the scan, and what the booking wrote."""
    code = GRAPH.replace("REQUEST", json.dumps(request)) + "\n" + page_code()
    return javascript("var result = (function () {\n" + code + "\nreturn {html: $.out, written: written}; })();")


def block(html: str, name: str):
    found = re.search(f'id="{name}">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


def form_of(html: str, action: str) -> str:
    (found,) = re.findall(r'<form class="inline"[^>]*>(?:(?!</form>).)*name="do" value="' + action + r'".*?</form>', html, re.S)
    return found


def value(form: str, name: str):
    found = re.search(r'<input [^>]*?name="' + name + r'"[^>]*?value="([^"]*)"', form)
    return found.group(1) if found else None


def selected(form: str, name: str):
    found = re.search(r'<select name="' + name + r'">.*?<option selected>([^<]*)</option>', form, re.S)
    return found.group(1) if found else None


def normalized_by_page(barcodes: list[str]) -> list:
    """What pages/lib/55_products.js normalizeBarcode makes of each: its GTIN, or its problem in words."""
    lib = page_code().split("// Shared by every page")[0]
    return javascript("var $ = {me: null, request: {}, find: function () { return []; }};\n" + lib + f"""
var result = {json.dumps(barcodes)}.map(function (b) {{
  try {{ return normalizeBarcode(b); }} catch (e) {{ return "! " + e.message; }} }});""")


def normalized_by_python(barcodes: list[str]) -> list:
    out = []
    for b in barcodes:
        try:
            out.append(normalize(b))
        except ValueError as exc:
            out.append(f"! {exc}")
    return out


@unittest.skipUnless(ENGINE, "no node or gjs")
class TheBarcodeAsThePageReadsIt(unittest.TestCase):
    def test_every_barcode_reads_as_products_normalize_reads_it(self):
        fixed = ["036000291452", "0 36000 29145 2", "0-36000-29145-2", "4006381333931", "73513537", "04252614",
                 "10036000291459", "01234505", "01234523", "14252611", "01234531", "01234543", "01234572",
                 "036000291453", "03600029145", "03600029145x", "", "  ", "212345678992", "412345678903",
                 "2012345678903", "20123451", "0400638133393"]
        rng = random.Random(20261123)        # random digits of every length, half with their check digit put right
        drawn = []
        for _ in range(400):
            digits = "".join(rng.choice("0123456789") for _ in range(rng.choice((7, 8, 12, 13, 14, 15))))
            if rng.random() < 0.5 and len(digits) > 1:
                body = digits[:-1]
                total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
                digits = body + str((10 - total % 10) % 10)
            drawn.append(digits)
        barcodes = fixed + drawn
        self.assertEqual(normalized_by_page(barcodes), normalized_by_python(barcodes))
        self.assertGreater(sum(1 for r in normalized_by_python(drawn) if not r.startswith("!")), 100)  # many read


@unittest.skipUnless(ENGINE, "no node or gjs")
class Scanning(unittest.TestCase):
    def test_a_known_barcode_fills_in_buy_with_its_product_and_one_package(self):
        for typed in ("036000291452", "0 36000 29145 2", "0036000291452"):
            got = page(scan=typed)
            self.assertEqual(block(got["html"], "scan-data"), {"gtin": "00036000291452", "product": "Farm eggs dozen",
                                                               "food": "Eggs", "amount": 12, "unit": "each"}, typed)
            buy = form_of(got["html"], "buy")
            self.assertEqual((value(buy, "food"), value(buy, "amount"), selected(buy, "unit"), value(buy, "scanning")),
                             ("Farm eggs dozen", "12", "each", "1"))
            self.assertIn("Farm eggs dozen <small>(Eggs)</small>: one package holds 12 each", got["html"])
            self.assertIn('placeholder="scan or type a barcode" autofocus>', got["html"])    # ready for the next
            self.assertEqual(got["written"], [])

    def test_a_unit_buy_does_not_offer_is_left_for_the_hand(self):
        got = page(scan="4006381333931")
        buy = form_of(got["html"], "buy")
        self.assertEqual(block(got["html"], "scan-data")["unit"], "fl oz")
        self.assertEqual((value(buy, "food"), value(buy, "amount"), selected(buy, "unit")), ("Jar of honey", None, "g"))

    def test_an_unknown_barcode_opens_add_a_product_with_it(self):
        got = page(scan="04252614")
        self.assertEqual(block(got["html"], "scan-data"), {"gtin": "00042100005264", "product": None, "food": None,
                                                           "amount": None, "unit": None})
        self.assertIn('<details class="product" open>', got["html"])
        self.assertEqual(value(form_of(got["html"], "product"), "barcode"), "04252614")
        self.assertIsNone(value(form_of(got["html"], "buy"), "food"))
        self.assertIn("No product has barcode 04252614 yet", got["html"])
        self.assertEqual(re.findall(r'<input name="(\w+)"[^>]* autofocus', got["html"]), ["name"])   # name it first

    def test_a_misread_or_shops_own_barcode_says_why(self):
        for typed, why in (("036000291453", "its last digit should be 2"), ("212345678992", "a shop's own number")):
            got = page(scan=typed)
            self.assertIn(why, block(got["html"], "scan-data")["problem"])
            self.assertIn('<p class="problem">Problem: barcode', got["html"])
            self.assertNotIn('<details class="product" open>', got["html"])

    def test_no_scan_leaves_the_page_as_it_was(self):
        got = page()
        self.assertIsNone(block(got["html"], "scan-data"))
        self.assertNotIn("autofocus", got["html"])         # a phone's keyboard does not pop up on every visit
        self.assertIn('<details class="product">', got["html"])


@unittest.skipUnless(ENGINE, "no node or gjs")
class AddingAProduct(unittest.TestCase):
    FORM = dict(do="product", token="abcd1234", barcode="04252614", name="Shop eggs six", food="Eggs", amount="6", unit="each")

    def test_a_new_product_is_written_below_its_food_and_buy_is_filled_in_with_it(self):
        got = page(**self.FORM)
        self.assertEqual(sorted(got["written"]), ["DefaultSpecification Shop eggs six package size", "DomainType Shop eggs six",
                                                  "Identifier GTIN 00042100005264",
                                                  "QuantitySpecification Shop eggs six package size value"])
        self.assertEqual(block(got["html"], "booking-data")["problem"], None)
        self.assertEqual(block(got["html"], "scan-data")["product"], "Shop eggs six")
        self.assertEqual(value(form_of(got["html"], "buy"), "food"), "Shop eggs six")
        self.assertIn("Shop eggs six (Eggs, 6 each a package) has barcode 00042100005264.", got["html"])

    def test_the_product_is_what_python_writes(self):
        code = GRAPH.replace("REQUEST", json.dumps(self.FORM)) + "\n" + page_code() + """
var t = $.find("DomainType", {name: "Shop eggs six"})[0], c = $.find("Identifier", {name: "GTIN 00042100005264"})[0];
var d = $.find("DefaultSpecification", {name: "Shop eggs six package size"})[0];
var vis = function (n) { return [n.visibleToAuthenticatedUsers, n.visibleToPublicUsers]; };
return [t.parent.name, t.hierarchy.name, t.isLookupBearing, vis(t), c.identifierValue, c.identifierScheme.name,
        c.denotesType.name, vis(c), d.forType.name, d.hasKind.name, d.hasValue.value, d.hasValue.unit, d.hasValue.status,
        d.provenance, d.source, vis(d)];"""
        got = javascript("var result = (function () {\n" + code + "\n})();")
        self.assertEqual(got, ["Eggs", "Food Identity", True, [True, False], "00042100005264", "GTIN", "Shop eggs six",
                               [True, False], "Shop eggs six", "PurchaseQuantity", 6, "each", "default", "sourced",
                               "the package, as entered on the pantry page", [True, False]])

    def test_another_barcode_of_a_product_writes_the_barcode_alone(self):
        got = page(**dict(self.FORM, name="Farm eggs dozen", amount="12"))
        self.assertEqual(got["written"], ["Identifier GTIN 00042100005264"])

    def test_what_cannot_be_added_is_named_kept_in_the_form_and_nothing_is_written(self):
        for change, expected in (
            (dict(name="Farm eggs dozen"), "Farm eggs dozen: one package of it holds 12 each already; a package of another "
                                           "size is another product, so name it apart"),
            (dict(name="Farm eggs dozen", amount="12", food="Noodles"), "Farm eggs dozen: it is a product of 'Eggs' already, not of 'Noodles'"),
            (dict(barcode="036000291452"), "Shop eggs six: barcode 00036000291452 already belongs to 'Farm eggs dozen'"),
            (dict(food="Beans"), "Shop eggs six: 'Beans' is a group of foods (Chickpeas), not a food that is bought; "
                                 "Shop eggs six: 6 each of Beans does not convert to grams (the food has no density or weight per item)"),
            (dict(food="Farm eggs dozen"), "Shop eggs six: 'Farm eggs dozen' is a product itself; name the food it is a kind of"),
            (dict(food="Egg"), "Shop eggs six: 'Egg' is not a food of this instance"),
            (dict(name="Eggs", food="Noodles"), "Eggs: that name is already a food here, not a product; "
                                                "Eggs: 6 each of Noodles does not convert to grams (the food has no density or weight per item)"),
            (dict(amount="0", barcode="036000291453"), "Shop eggs six: what a package holds (amount) must be more than 0; "
                                                       "Shop eggs six: barcode '036000291453' is misread or mistyped: its last digit should be 2"),
            (dict(name="Eggs, six"), "Eggs, six: a name cannot hold a comma or a semicolon"),
        ):
            got = page(**dict(self.FORM, **change))
            self.assertEqual(block(got["html"], "booking-data")["problem"], expected, change)
            self.assertEqual(got["written"], [], change)
            form = form_of(got["html"], "product")
            self.assertIn('<details class="product" open>', got["html"])
            self.assertEqual((value(form, "name"), value(form, "barcode")),
                             (change.get("name", "Shop eggs six"), change.get("barcode", "04252614")))
            self.assertIsNone(block(got["html"], "scan-data"))


if __name__ == "__main__":
    unittest.main()
