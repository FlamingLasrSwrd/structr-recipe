"""The pantry page's food picker (pages/files/mealplanner-foods.js, pages/pantry.js; docs/pantry.md, "Choosing
the food"): a food is named exactly as the instance names it, so each food box searches the names it takes as
you type, and "Add a product" shows the foods an Open Food Facts product likely is, to tap.

  what it finds: words, search and guess, run in node over names chosen here, each expected value worked
              out by hand from the rules in the file's comments
  in a browser: Chromium through Playwright, where node has it, over pages/pantry.js printed on
              tests/test_pantry_scan.py's stand-in graph (its foods: Eggs, Noodles, Chickpeas below the group
              Beans, Honey; its products Farm eggs dozen, of 12 each, and Jar of honey), Open Food Facts
              answered by the test
"""

import json
import os
import subprocess
import tempfile
import unittest

from tests.test_pantry_camera import NODE, browser_can_run
from tests.test_pantry_lookup import CHICKPEAS, ROOT, UNKNOWN, installed_page
from tests.test_signed_out import ENGINE, javascript

FOODS = ROOT / "pages" / "files" / "mealplanner-foods.js"
NAMES = ["Chickpeas (canned)", "Chickpeas (canned drained)", "Chicken Breast (raw)", "Chicken broth", "Diced tomatoes (canned)",
         "Tomato", "Tomato paste", "Peanut butter (creamy)", "Butter (salted)", "Rolled oats", "Potatoes", "Purée de pommes",
         "Whole milk", "Coconut milk (canned)", "Egg"]


def foods(call: str):
    return javascript(f"var api = require({json.dumps(str(FOODS))});\nvar names = {json.dumps(NAMES)};\nvar result = {call};")


@unittest.skipUnless(NODE, "no node")
class WhatItFinds(unittest.TestCase):
    def test_words_are_compared_without_case_accents_or_plurals(self):
        self.assertEqual(foods('["Purée de POMMES", "Tomatoes, diced", "berries", "peas", "glass", "bus"].map(api.words)'),
                         [["puree", "de", "pomme"], ["tomato", "diced"], ["berry"], ["pea"], ["glass"], ["bus"]])

    def test_typing_finds_each_word_as_the_start_of_one_in_any_order(self):
        cases = {
            "chick": ["Chicken broth", "Chickpeas (canned)", "Chicken Breast (raw)", "Chickpeas (canned drained)"],
            "canned chickpea": ["Chickpeas (canned)", "Chickpeas (canned drained)"],        # in any order
            "TOMATOES DICED": ["Diced tomatoes (canned)"],
            "tomato": ["Tomato", "Tomato paste", "Diced tomatoes (canned)"],    # begins so first, then shorter
            "puree": ["Purée de pommes"], "milk": ["Whole milk", "Coconut milk (canned)"],
            "pb": [], "": [], "  ": [],
        }
        got = foods(f"{json.dumps(list(cases))}.map(function (q) {{ return api.search(names, q); }})")
        self.assertEqual(dict(zip(cases, got)), cases)
        self.assertEqual(foods('api.search(names.concat(["Food 1", "Food 2", "Food 3", "Food 4", "Food 5", "Food 6", "Food 7", '
                               '"Food 8", "Food 9"]), "food").length'), 8)       # no more than 8 shown

    def test_the_foods_a_product_likely_is(self):
        cases = [
            ({"name": "Chickpeas", "categories": ["Plant based foods", "Legumes", "Canned legumes", "Chickpeas"]},
             ["Chickpeas (canned)", "Chickpeas (canned drained)"]),        # 10+5+3 = 18; 10+5+3-1 = 17
            ({"name": "Creamy Peanut Butter", "categories": ["Spreads", "Nut butters", "Peanut butters"]},
             ["Peanut butter (creamy)"]),                                   # 28; Butter (salted) 10+5-1 = 14 is too far below
            ({"name": "Rolled Oats", "categories": ["Cereals and potatoes", "Breakfast cereals", "Rolled oats"]},
             ["Rolled oats"]),                                             # 25; Potatoes 15
            ({"name": "Diced Tomatoes", "categories": ["Canned foods", "Canned tomatoes", "Diced tomatoes"]},
             ["Diced tomatoes (canned)"]),                                 # 28; Tomato 15
            ({"name": "Large Brown Eggs", "categories": ["Farming products", "Eggs"]}, ["Egg"]),
            ({"name": "Kombucha", "categories": ["Beverages", "Fermented drinks"]}, []),
            ({}, []),
        ]
        got = foods(f"{json.dumps([c for c, _ in cases])}.map(function (o) {{ return api.guess(names, o); }})")
        for (off, want), seen in zip(cases, got):
            self.assertEqual(seen, want, off)


@unittest.skipUnless(ENGINE, "no node or gjs")
class ThePage(unittest.TestCase):
    def test_the_picker_is_loaded_where_installed_and_the_lists_stay_for_a_browser_without_it(self):
        html = installed_page()
        self.assertIn('<script src="/mealplanner/mealplanner-foods.js?v=44" defer></script>', html)
        self.assertIn('list="foods"', html)
        self.assertIn('list="product-foods"', html)


DRIVER = r"""
const { chromium } = require('playwright');
const [origin, page_html, off, steps] = JSON.parse(process.argv[process.argv.length - 1]);
const fs = require('fs');
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  page.on('pageerror', (e) => console.error('PAGEERROR ' + e));
  const out = {sent: null, seen: []};
  await page.route('https://world.openfoodfacts.org/**', (route) => off
    ? route.fulfill({status: 200, contentType: 'application/json', headers: {'Access-Control-Allow-Origin': '*'}, body: JSON.stringify(off)})
    : route.abort('failed'));
  await page.route(origin + '/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/structr/html/pantry' && url.searchParams.get('do')) {
      out.sent = Object.fromEntries(url.searchParams.entries());
      return route.fulfill({contentType: 'text/html', body: '<p>sent</p>'});
    }
    if (url.pathname === '/structr/html/pantry') return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><head></head><body>' + page_html + '</body></html>'});
    if (url.pathname.startsWith('/mealplanner/')) return route.fulfill({contentType: 'text/javascript', body: fs.readFileSync(process.env.FILES + url.pathname.slice(13))});
    return route.fulfill({status: 404, body: ''});
  });
  await page.goto(origin + '/structr/html/pantry');
  for (const [what, where, value] of steps) {
    const box = 'details.' + where + ' input[name=food]';
    if (what === 'open') await page.click('details.' + where + ' summary');
    else if (what === 'type') await page.fill(box, value);
    else if (what === 'tap') await page.click('details.' + where + ' div.picks button:text-is(' + JSON.stringify(value) + ')');
    else if (what === 'enter') await page.press(box, 'Enter');
    else if (what === 'wait') await page.waitForSelector('details.' + where + ' div.picks.likely:not([hidden])', {timeout: 15000}).catch(() => null);
    else if (what === 'send') await Promise.all([page.waitForURL(/do=/), page.click('details.' + where + ' form button:not([type=button])')]);
    else if (what === 'fill') await page.fill('details.' + where + ' [name=' + value[0] + ']', value[1]);
    if (what !== 'send' && what !== 'open') out.seen.push(await page.evaluate((w) => {
      const d = document.querySelector('details.' + w);
      const row = (c) => { const r = d.querySelector('div.picks.' + c); return r && !r.hidden ? Array.from(r.querySelectorAll('button')).map((b) => b.textContent) : null; };
      const found = d.querySelector('div.picks.found');
      return {food: d.querySelector('input[name=food]').value, list: d.querySelector('input[name=food]').getAttribute('list'),
              found: row('found'), likely: row('likely'), said: found && !found.hidden && !found.querySelector('button') ? found.textContent : null,
              unit: (d.querySelector('select[name=unit]') || {}).value};
    }, where));
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(browser_can_run(), "needs node with Playwright and its Chromium")
class InABrowser(unittest.TestCase):
    def drive(self, steps, html=None, off=None) -> dict:
        args = json.dumps(["https://pantry.test", html or installed_page(), off, steps])
        done = subprocess.run([NODE, "-e", DRIVER, args], capture_output=True, text=True, timeout=120, cwd=tempfile.gettempdir(),
                              env={**os.environ, "FILES": str(ROOT / "pages" / "files") + "/"})
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_typing_in_buy_finds_foods_and_a_tap_puts_the_name_in_and_picks_its_unit(self):
        got = self.drive([["type", "buy", "farm"], ["tap", "buy", "Farm eggs dozen"]])
        typed, tapped = got["seen"]
        self.assertEqual((typed["list"], typed["found"]), (None, ["Farm eggs dozen"]))      # the browser's own list is gone
        self.assertEqual((tapped["food"], tapped["found"], tapped["unit"]), ("Farm eggs dozen", None, "each"))

    def test_add_a_product_offers_only_foods_a_product_may_be(self):
        got = self.drive([["open", "product", None], ["type", "product", "e"], ["type", "product", "zzz"]])
        self.assertEqual(got["seen"][0]["found"], ["Eggs"])         # not the product Farm eggs dozen
        self.assertEqual((got["seen"][1]["found"], got["seen"][1]["said"]),
                         ([], "No food here is named like that: try a shorter or other word."))

    def test_enter_takes_the_first_found_and_another_case_is_put_right_when_sent(self):
        got = self.drive([["open", "product", None], ["type", "product", "chick"], ["enter", "product", None]])
        self.assertEqual(got["seen"][1]["food"], "Chickpeas")
        got = self.drive([["open", "product", None], ["fill", "product", ["barcode", UNKNOWN]], ["fill", "product", ["name", "Our chickpeas"]],
                          ["fill", "product", ["amount", "400"]], ["type", "product", "chickpeas"], ["send", "product", None]])
        self.assertEqual(got["sent"]["food"], "Chickpeas")

    def test_the_foods_a_looked_up_product_likely_is_are_offered_never_chosen(self):
        got = self.drive([["wait", "product", None], ["tap", "product", "Chickpeas"]], html=installed_page(scan=UNKNOWN), off=CHICKPEAS)
        offered, tapped = got["seen"]
        self.assertEqual((offered["likely"], offered["food"]), (["Chickpeas"], ""))     # offered, the box left empty
        self.assertEqual((tapped["food"], tapped["likely"]), ("Chickpeas", None))

    def test_nothing_is_offered_where_open_food_facts_cannot_be_reached(self):
        got = self.drive([["wait", "product", None]], html=installed_page(scan=UNKNOWN), off=None)
        self.assertIsNone(got["seen"][0]["likely"])


if __name__ == "__main__":
    unittest.main()
