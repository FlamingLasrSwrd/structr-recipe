// The pantry page's look-up of an unknown barcode on Open Food Facts (docs/pantry.md, "Looking up an
// unknown barcode"). Served as a file (tools/install_pages.py puts pages/files/ in Structr's folder
// /mealplanner/), run in the browser.
//
// When a scanned barcode is no product's, the page opens "Add a product" with it and marks it
// (p.lookup[data-lookup], the barcode as its GTIN). This asks Open Food Facts what it knows of that
// barcode, from the browser, sending the barcode and nothing else of the instance (no cookie, no referrer),
// and fills in what is still empty: the name (brand, name and size, as on the package) and what one package
// holds. It never chooses the food: which food a product is a kind of is the user's judgment (J19), so it
// shows the categories Open Food Facts files it under as a hint. A package size taken from Open Food Facts
// is recorded as sourced there (the form's source field, "off"), until the amount or unit is changed by hand.
//
// The same file runs in node for tests/test_pantry_lookup.py, which reads offCode, parseQuantity and fromOff.
(function () {
  "use strict";
  var API = "https://world.openfoodfacts.org/api/v2/product/";
  var SITE = "https://world.openfoodfacts.org/product/";
  var FIELDS = ["code", "product_name", "product_name_en", "generic_name", "generic_name_en", "brands", "quantity",
                "product_quantity", "product_quantity_unit", "categories_tags"];
  var WAIT_MS = 10000;
  // The units printed on packages, as the page's units (pages/lib/50_pantry.js UNITS) and a factor
  var UNIT_WORDS = [
    [["kilograms", "kilogram", "kilos", "kilo", "kgs", "kg"], "kg", 1],
    [["milligrams", "milligram", "mg"], "g", 0.001],
    [["grammes", "gramme", "grams", "gram", "gr", "g"], "g", 1],
    [["floz"], "fl_oz", 1],
    [["ounces", "ounce", "oz"], "oz", 1],
    [["pounds", "pound", "lbs", "lb"], "lb", 1],
    [["millilitres", "milliliters", "millilitre", "milliliter", "ml"], "ml", 1],
    [["centilitres", "centiliters", "cl"], "ml", 10],
    [["decilitres", "deciliters", "dl"], "ml", 100],
    [["litres", "liters", "litre", "liter", "ltr", "lt", "l"], "l", 1],
    [["pieces", "piece", "pcs", "pc", "count", "ct", "units", "unit", "eggs", "each"], "each", 1],
  ];
  var WORD = {};
  UNIT_WORDS.forEach(function (row) { row[0].forEach(function (w) { WORD[w] = [row[1], row[2]]; }); });
  var WORDS = Object.keys(WORD).sort(function (a, b) { return b.length - a.length; }).join("|");
  var NUM = "(\\d+(?:[.,]\\d+)?)";
  var MULTI = new RegExp("(\\d+)\\s*x\\s*" + NUM + "\\s*(" + WORDS + ")(?![a-z])");
  var ONE = new RegExp(NUM + "\\s*(" + WORDS + ")(?![a-z])");

  // The code Open Food Facts files a GTIN under: 8 digits for an EAN-8, 13 for an EAN-13 or a UPC-A (a 0
  // before its 12), else all 14
  function offCode(gtin) {
    var g = String(gtin);
    if (/^000000\d{8}$/.test(g)) return g.slice(6);
    if (/^0\d{13}$/.test(g)) return g.slice(1);
    return g;
  }

  // "1,5" and "1.5" are one and a half; "1,000" is a thousand
  function number(text) {
    if (/^\d+,\d{3}$/.test(text)) return Number(text.replace(",", ""));
    return Number(text.replace(",", "."));
  }

  function round(x) { return Math.round(x * 1000) / 1000; }

  // What one package holds, read from a label's words ("400 g", "6 x 330 ml", "16 oz (1 lb) 454 g",
  // "12 eggs"): {amount, unit} in the page's units, or null where no amount with a unit is in it
  function parseQuantity(text) {
    if (text == null) return null;
    var t = String(text).toLowerCase().replace(/\u00d7/g, "x").replace(/fl\.?\s*oz\.?/g, "floz");
    var m = MULTI.exec(t);
    if (m) {
      var each = WORD[m[3]];
      return {amount: round(Number(m[1]) * number(m[2]) * each[1]), unit: each[0]};
    }
    m = ONE.exec(t);
    if (!m) return null;
    var unit = WORD[m[2]], amount = round(number(m[1]) * unit[1]);
    return amount > 0 ? {amount: amount, unit: unit[0]} : null;
  }

  // A size as the page writes it in a name: "400 g", "12 fl oz"
  function sizeLabel(size) {
    return size.amount + " " + (size.unit === "fl_oz" ? "fl oz" : size.unit);
  }

  function clean(text) {
    return String(text == null ? "" : text).replace(/[,;]/g, " ").replace(/\s+/g, " ").trim();
  }

  // What the form is filled in with from Open Food Facts' product: {name, amount, unit, categories}, each
  // null (or empty) where it gives none. A name holds no comma or semicolon (products.parse_products).
  // For guessing the food (mealplanner-foods.js guess): title, its name without brand or size, and tags,
  // every category in English, most particular first.
  function fromOff(product) {
    product = product || {};
    var title = clean(product.product_name_en || product.product_name || product.generic_name_en || product.generic_name);
    var brand = clean(String(product.brands || "").split(",")[0]);
    var size = parseQuantity(product.quantity);
    if (!size) {
      var held = Number(product.product_quantity), unit = String(product.product_quantity_unit || "g").toLowerCase();
      if (held > 0 && (unit === "g" || unit === "ml")) size = {amount: round(held), unit: unit};
    }
    var name = title;
    if (brand && name.toLowerCase().indexOf(brand.toLowerCase()) < 0) name = clean(brand + " " + name);
    if (name && size && name.indexOf(String(size.amount)) < 0) name = name + " " + sizeLabel(size);
    var categories = (product.categories_tags || []).filter(function (c) { return /^en:/.test(c); })
      .map(function (c) { var w = c.slice(3).replace(/-/g, " "); return w.charAt(0).toUpperCase() + w.slice(1); });
    return {name: name.slice(0, 100) || null, amount: size ? size.amount : null, unit: size ? size.unit : null,
            categories: categories.slice(-3).reverse(), title: title || null, tags: categories.slice().reverse()};
  }

  var api = {API: API, FIELDS: FIELDS, offCode: offCode, parseQuantity: parseQuantity, fromOff: fromOff};
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  var form = document.querySelector("details.product form");
  if (!form) return;
  var source = form.querySelector("input[name=source]");
  var amount = form.querySelector("input[name=amount]"), unit = form.querySelector("select[name=unit]");
  var nameBox = form.querySelector("input[name=name]"), foodBox = form.querySelector("input[name=food]");
  var filled = null;              // the amount and unit Open Food Facts gave, while they stand
  // A size changed by hand is the package's, entered on the page, no longer Open Food Facts'
  function handChanged() {
    if (!source || source.value !== "off") return;
    if (!filled || amount.value !== String(filled.amount) || unit.value !== filled.unit) source.value = "";
  }
  if (source && source.value === "off") filled = {amount: amount.value, unit: unit.value};
  amount.addEventListener("input", handChanged);
  unit.addEventListener("change", handChanged);
  // and Open Food Facts said nothing of another barcode
  form.querySelector("input[name=barcode]").addEventListener("input", function () {
    filled = null;
    if (source) source.value = "";
  });

  var note = document.querySelector("p.lookup[data-lookup]");
  if (!note || typeof fetch !== "function") return;
  var code = offCode(note.getAttribute("data-lookup"));
  function say(text) { note.textContent = text; note.hidden = false; }
  say("Looking up barcode " + code + " on Open Food Facts (only the barcode is sent)...");
  var stop = typeof AbortController === "function" ? new AbortController() : null;
  var timer = setTimeout(function () { if (stop) stop.abort(); }, WAIT_MS);
  fetch(API + encodeURIComponent(code) + ".json?fields=" + FIELDS.join(","),
        {credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store", signal: stop ? stop.signal : undefined})
    .then(function (r) {
      if (r.status === 404) return {status: 0};
      if (!r.ok) throw new Error("it answered " + r.status);
      return r.json();
    })
    .then(function (data) {
      clearTimeout(timer);
      if (!data || data.status !== 1 || !data.product) {
        say("Open Food Facts doesn't know barcode " + code + ". Fill in the details from the package.");
        return;
      }
      var got = fromOff(data.product), typed = nameBox.value.trim() !== "";
      if (got.name && !typed) nameBox.value = got.name;
      var sized = false;
      if (got.amount != null && amount.value === "" &&
          Array.prototype.some.call(unit.options, function (o) { return o.value === got.unit; })) {
        amount.value = String(got.amount);
        unit.value = got.unit;
        filled = {amount: amount.value, unit: unit.value};
        if (source) source.value = "off";
        sized = true;
      }
      note.textContent = "";
      note.appendChild(document.createTextNode("From Open Food Facts: " + (got.name || "no name") + ". "
        + (sized ? "" : "It gives no size this page can use, so enter what one package holds. ")
        + "Check it against the package, then choose the food it is a kind of"
        + (got.categories.length ? " (it files it under " + got.categories.join("; ") + ")" : "") + ". "));
      var link = document.createElement("a");
      link.href = SITE + encodeURIComponent(code);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Its page there";
      note.appendChild(link);
      note.hidden = false;
      // the foods it likely is, to tap (mealplanner-foods.js), where none is chosen yet
      var foods = window.mealplannerFoods;
      if (foods && foodBox && !foodBox.value.trim()) {
        foods.offer(foodBox, foods.guess(foods.namesOf(foodBox), {name: got.title, categories: got.tags}));
      }
      if (!typed && got.name && document.activeElement === nameBox && foodBox) foodBox.focus();
    })
    .catch(function (e) {
      clearTimeout(timer);
      say("Open Food Facts could not be reached (" + (e && e.name === "AbortError" ? "no answer in "
          + WAIT_MS / 1000 + " seconds" : (e && e.message) || "no answer") + "): fill it in from the package.");
    });
})();
