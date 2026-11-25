"""The pantry page's look-up of an unknown barcode on Open Food Facts (pages/files/mealplanner-lookup.js,
pages/pantry.js; docs/pantry.md, "Looking up an unknown barcode").

  what it reads: the label's words for what one package holds, and the name it builds, run in node over
              products shaped as Open Food Facts gives them, each expected value worked out by hand
  the page: the barcode to look up is marked only where no product has it, with the look-up installed,
              and a size kept from Open Food Facts is sourced there when the product is added
  in a browser: Chromium through Playwright, where node has it, the page served at a made-up address and
              Open Food Facts answered by the test: what is filled in and what is left alone, what is
              said when it does not know the barcode or cannot be reached, and that only the barcode is
              sent, with no cookie and no referrer, and nothing at all for a known barcode or a plain visit

The page is pages/pantry.js printed over tests/test_pantry_scan.py's stand-in graph, where the UPC-E
04252614 (GTIN 00042100005264, spelled out to the UPC-A 042100005264) is no product's and the UPC-A
036000291452 is Farm eggs dozen's.
"""

import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

from tests.test_pantry_buy_unit import page_code
from tests.test_pantry_camera import NODE, browser_can_run
from tests.test_pantry_scan import GRAPH, block, form_of, page, value
from tests.test_signed_out import ENGINE, javascript

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOOKUP = ROOT / "pages" / "files" / "mealplanner-lookup.js"
UNKNOWN, GTIN, OFF_CODE = "04252614", "00042100005264", "0042100005264"
INSTALLED = """
node("File", "mealplanner-camera.js", {path: "/mealplanner/mealplanner-camera.js", checksum: 11});
node("File", "zxing-library-0.23.0.min.js", {path: "/mealplanner/zxing-library-0.23.0.min.js", checksum: 22});
node("File", "mealplanner-lookup.js", {path: "/mealplanner/mealplanner-lookup.js", checksum: 33});
node("File", "mealplanner-foods.js", {path: "/mealplanner/mealplanner-foods.js", checksum: 44});"""


def lookup(call: str):
    """What `call` returns, run in node over the look-up's own functions."""
    return javascript(f"var api = require({json.dumps(str(LOOKUP))});\nvar result = {call};")


def installed_page(**request) -> str:
    code = GRAPH.replace("REQUEST", json.dumps(request)) + INSTALLED + "\n" + page_code()
    return javascript("var result = (function () {\n" + code + "\nreturn $.out; })();")


@unittest.skipUnless(NODE, "no node")
class WhatItReads(unittest.TestCase):
    def test_what_one_package_holds_from_the_labels_words(self):
        cases = {
            "400 g": [400, "g"], "400g": [400, "g"], "100 Gr": [100, "g"], "250 grams": [250, "g"],
            "1,5 kg": [1.5, "kg"], "1,000 g": [1000, "g"], "500 mg": [0.5, "g"],      # 500 x 0.001
            "1.5 L": [1.5, "l"], "75cl": [750, "ml"],                                 # 75 x 10
            "6 x 330 ml": [1980, "ml"], "6 × 33 cl": [1980, "ml"],                   # 6 x 330; 6 x 33 x 10
            "16 oz (1 lb) 454 g": [16, "oz"], "12 fl. oz": [12, "fl_oz"], "2 lbs": [2, "lb"],
            "12 eggs": [12, "each"], "10 pcs": [10, "each"],
            "big pack": None, "12": None, "": None, "1 gallon": None,
        }
        got = lookup(f"{json.dumps(list(cases))}.map(function (t) {{ var q = api.parseQuantity(t); return q && [q.amount, q.unit]; }})")
        self.assertEqual(dict(zip(cases, got)), cases)
        self.assertIsNone(lookup("api.parseQuantity(null)"))

    def test_the_code_open_food_facts_files_a_gtin_under(self):
        self.assertEqual(lookup('["00042100005264", "00000073513537", "04006381333931", "10036000291459"].map(api.offCode)'),
                         ["0042100005264", "73513537", "4006381333931", "10036000291459"])

    def test_the_name_size_and_categories_it_fills_in(self):
        products = [
            ({"product_name": "Chickpeas", "brands": "Brand X, Parent Co", "quantity": "400 g",
              "categories_tags": ["en:plant-based-foods", "en:legumes", "en:chickpeas", "fr:pois-chiches"]},
             {"name": "Brand X Chickpeas 400 g", "amount": 400, "unit": "g",
              "categories": ["Chickpeas", "Legumes", "Plant based foods"],            # most specific first, English only
              "title": "Chickpeas", "tags": ["Chickpeas", "Legumes", "Plant based foods"]}),
            ({"product_name": "Brand X chickpeas, salted", "brands": "brand x", "quantity": "400g"},
             {"name": "Brand X chickpeas salted 400 g", "amount": 400, "unit": "g", "categories": [],     # brand named once
              "title": "Brand X chickpeas salted", "tags": []}),
            ({"product_name": "Oat drink 1L", "product_name_en": "Oat drink 1L", "quantity": "1 l"},
             {"name": "Oat drink 1L", "amount": 1, "unit": "l", "categories": [], "title": "Oat drink 1L", "tags": []}),
            ({"product_name": "Haferdrink", "product_name_en": "Oat drink", "product_quantity": "750", "product_quantity_unit": "ml"},
             {"name": "Oat drink 750 ml", "amount": 750, "unit": "ml", "categories": [], "title": "Oat drink", "tags": []}),
            ({"product_name": "Tea; green", "product_quantity": 454},
             {"name": "Tea green 454 g", "amount": 454, "unit": "g", "categories": [], "title": "Tea green", "tags": []}),
            ({"product_name": "Crackers", "quantity": "a box"},
             {"name": "Crackers", "amount": None, "unit": None, "categories": [], "title": "Crackers", "tags": []}),
            ({}, {"name": None, "amount": None, "unit": None, "categories": [], "title": None, "tags": []}),
        ]
        got = lookup(f"{json.dumps([p for p, _ in products])}.map(api.fromOff)")
        for (product, want), seen in zip(products, got):
            self.assertEqual(seen, want, product)


@unittest.skipUnless(ENGINE, "no node or gjs")
class ThePage(unittest.TestCase):
    def test_an_unknown_barcode_is_marked_for_the_look_up(self):
        html = installed_page(scan=UNKNOWN)
        self.assertIn(f'<p class="lookup note" data-lookup="{GTIN}" hidden></p>', html)
        self.assertIn('<script src="/mealplanner/mealplanner-lookup.js?v=33" defer></script>', html)
        self.assertEqual(value(form_of(html, "product"), "source"), "")

    def test_nothing_is_looked_up_for_a_known_barcode_a_plain_visit_or_without_the_file(self):
        for html in (installed_page(scan="036000291452"), installed_page(), page(scan=UNKNOWN)["html"]):
            self.assertNotIn("data-lookup", html)
        self.assertNotIn("mealplanner-lookup.js", page(scan=UNKNOWN)["html"])

    def test_a_size_kept_from_open_food_facts_is_sourced_there(self):
        form = dict(do="product", token="abcd1234", barcode=UNKNOWN, name="Shop eggs six", food="Eggs", amount="6", unit="each")
        sources = {}
        for sent in ("off", "", "anything else"):
            code = GRAPH.replace("REQUEST", json.dumps(dict(form, source=sent))) + "\n" + page_code() + """
return $.find("DefaultSpecification", {name: "Shop eggs six package size"})[0].source;"""
            sources[sent] = javascript("var result = (function () {\n" + code + "\n})();")
        self.assertEqual(sources, {"off": f"Open Food Facts, barcode {GTIN}, as checked on the pantry page",
                                   "": "the package, as entered on the pantry page",
                                   "anything else": "the package, as entered on the pantry page"})

    def test_a_refused_product_keeps_its_source_in_the_form(self):
        got = page(do="product", token="abcd1234", barcode=UNKNOWN, name="Shop eggs six", food="Egg", amount="6", unit="each",
                   source="off")
        self.assertIn("'Egg' isn't a food the planner knows; check the spelling", block(got["html"], "booking-data")["problem"])
        self.assertEqual(value(form_of(got["html"], "product"), "source"), "off")
        self.assertNotIn("data-lookup", got["html"])          # what the user sent is kept; nothing is looked up again


DRIVER = r"""
const { chromium } = require('playwright');
const [origin, page_html, off, typeFirst, change, submit] = JSON.parse(process.argv[process.argv.length - 1]);
const fs = require('fs');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  await context.addCookies([{name: 'JSESSIONID', value: 'secret-session', url: origin}, {name: 'session', value: 'theirs', url: 'https://world.openfoodfacts.org'}]);
  const page = await context.newPage();
  const out = {asked: [], sent: null};
  await context.route('https://world.openfoodfacts.org/**', async (route) => {
    const r = route.request();
    out.asked.push({url: r.url(), headers: await r.allHeaders()});
    if (off.delay) await new Promise((ok) => setTimeout(ok, off.delay));
    if (off.abort) return route.abort('failed');
    return route.fulfill({status: off.status || 200, contentType: 'application/json',
                          headers: {'Access-Control-Allow-Origin': '*'}, body: JSON.stringify(off.body)});
  });
  await context.route(origin + '/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/structr/html/pantry' && url.searchParams.get('do') === 'product') {
      out.sent = Object.fromEntries(url.searchParams.entries());
      return route.fulfill({contentType: 'text/html', body: '<p>added</p>'});
    }
    if (url.pathname === '/structr/html/pantry') return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><head></head><body>' + page_html + '</body></html>'});
    if (url.pathname.startsWith('/mealplanner/')) return route.fulfill({contentType: 'text/javascript', body: fs.readFileSync(process.env.FILES + url.pathname.slice(13))});
    return route.fulfill({status: 404, body: ''});
  });
  await page.goto(origin + '/structr/html/pantry');
  if (typeFirst) await page.fill('details.product input[name=name]', typeFirst);
  const note = 'p.lookup';
  try {
    await page.waitForFunction(() => { const p = document.querySelector('p.lookup');
      return p && p.textContent && p.textContent.indexOf('Looking up') < 0; }, null, {timeout: off.never ? 2000 : 15000});
  } catch (e) { out.waited = true; }
  if (change) await page.fill('details.product input[name=' + change[0] + ']', change[1]);
  const field = (n) => page.$eval('details.product [name=' + n + ']', (e) => e.value);
  out.fields = {name: await field('name'), food: await field('food'), amount: await field('amount'), unit: await field('unit'),
                source: await field('source')};
  out.note = await page.$eval(note, (p) => ({text: p.textContent, hidden: p.hidden, elements: Array.from(p.querySelectorAll('*')).map((c) => c.tagName),
                                              link: (p.querySelector('a') || {}).href || null})).catch(() => null);
  out.focused = await page.evaluate(() => document.activeElement && document.activeElement.name);
  if (submit) {
    await page.fill('details.product input[name=food]', 'Chickpeas');
    await Promise.all([page.waitForURL(/do=product/), page.click('details.product button')]);
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""

CHICKPEAS = {"code": OFF_CODE, "status": 1, "product": {
    "product_name": "Chickpeas", "brands": "Brand X", "quantity": "400 g",
    "categories_tags": ["en:legumes", "en:chickpeas"]}}


@unittest.skipUnless(browser_can_run(), "needs node with Playwright and its Chromium")
class InABrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unknown = installed_page(scan=UNKNOWN)

    def drive(self, off, html=None, type_first=None, change=None, submit=False) -> dict:
        args = json.dumps(["https://pantry.test", html or self.unknown, off, type_first, change, submit])
        done = subprocess.run([NODE, "-e", DRIVER, args], capture_output=True, text=True, timeout=120, cwd=tempfile.gettempdir(),
                              env={**os.environ, "FILES": str(ROOT / "pages" / "files") + "/"})
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_what_open_food_facts_knows_is_filled_in_and_the_food_left_to_the_user(self):
        got = self.drive({"body": CHICKPEAS}, submit=True)
        self.assertEqual(got["fields"], {"name": "Brand X Chickpeas 400 g", "food": "", "amount": "400", "unit": "g",
                                         "source": "off"})
        self.assertIn("From Open Food Facts: Brand X Chickpeas 400 g.", got["note"]["text"])
        self.assertIn("choose the food it is a kind of (it files it under Chickpeas; Legumes)", got["note"]["text"])
        self.assertEqual(got["note"]["link"], f"https://world.openfoodfacts.org/product/{OFF_CODE}")
        self.assertFalse(got["note"]["hidden"])
        self.assertEqual(got["focused"], "food")                 # what is left for the user
        self.assertEqual((got["sent"]["source"], got["sent"]["name"], got["sent"]["barcode"]), ("off", "Brand X Chickpeas 400 g", UNKNOWN))

    def test_only_the_barcode_is_sent(self):
        got = self.drive({"body": CHICKPEAS})
        (asked,) = got["asked"]
        self.assertTrue(asked["url"].startswith(f"https://world.openfoodfacts.org/api/v2/product/{OFF_CODE}.json?fields="), asked)
        self.assertEqual(re.sub(r"fields=[a-z_,]*", "", asked["url"].split("?", 1)[1]), "")   # nothing else in the address
        headers = {k.lower() for k in asked["headers"]}
        self.assertNotIn("cookie", headers)
        self.assertNotIn("referer", headers)

    def test_a_name_typed_while_waiting_is_kept(self):
        got = self.drive({"body": CHICKPEAS, "delay": 1500}, type_first="Our chickpeas")
        self.assertEqual((got["fields"]["name"], got["fields"]["amount"], got["fields"]["source"]), ("Our chickpeas", "400", "off"))

    def test_a_size_changed_by_hand_is_no_longer_sourced_there(self):
        got = self.drive({"body": CHICKPEAS}, change=["amount", "425"])
        self.assertEqual((got["fields"]["amount"], got["fields"]["source"]), ("425", ""))

    def test_another_barcode_typed_in_is_no_longer_sourced_there(self):
        got = self.drive({"body": CHICKPEAS}, change=["barcode", "036000291452"])
        self.assertEqual((got["fields"]["amount"], got["fields"]["source"]), ("400", ""))

    def test_without_a_size_it_says_so_and_its_words_are_shown_as_words(self):
        got = self.drive({"body": {"status": 1, "product": {"product_name": "<b>Tea</b>", "quantity": "a box"}}})
        self.assertEqual(got["fields"], {"name": "<b>Tea</b>", "food": "", "amount": "", "unit": "g", "source": ""})
        self.assertIn("It gives no size this page can use", got["note"]["text"])
        self.assertEqual(got["note"]["elements"], ["A"])          # its link alone: the name was not read as HTML

    def test_a_barcode_it_does_not_know(self):
        got = self.drive({"status": 404, "body": {"status": 0, "status_verbose": "product not found"}})
        self.assertEqual(got["note"]["text"], f"Open Food Facts doesn't know barcode {OFF_CODE}. Fill in the details from the package.")
        self.assertEqual(got["fields"], {"name": "", "food": "", "amount": "", "unit": "g", "source": ""})

    def test_when_it_cannot_be_reached(self):
        got = self.drive({"abort": True})
        self.assertTrue(got["note"]["text"].startswith("Open Food Facts could not be reached ("), got["note"])
        self.assertTrue(got["note"]["text"].endswith("): fill it in from the package."), got["note"])
        self.assertEqual(got["fields"]["source"], "")

    def test_nothing_is_sent_for_a_known_barcode_or_a_plain_visit(self):
        for html in (installed_page(scan="036000291452"), installed_page()):
            got = self.drive({"body": CHICKPEAS, "never": True}, html=html)
            self.assertEqual(got["asked"], [])


if __name__ == "__main__":
    unittest.main()
