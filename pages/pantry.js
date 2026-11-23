// /structr/html/pantry: the stock on hand now and when it expires, soonest first, as mealplanner/inventory.py
// works them out: the latest weighing less every use since (current_magnitude), and the shelf life of
// its perishability where it is kept, from when it was bought or first weighed (instance_expiration).
//
// Its forms book what happens to it, as mealplanner/pantry.py does (docs/pantry.md): buy, use, count
// (a stock take), open, move (freeze) and discard. Each sends ?do=<booking>&token=<one per form>.
// The bookings themselves are in pages/lib/50_pantry.js (PANTRY_ACTIONS), shared with the bookPantry method.
//
// A barcode scanned or typed into Buy's barcode box (?scan=..., docs/pantry.md "Products and barcodes")
// fills Buy in with the product it names and what one package holds, as products.find reads it; a
// barcode no product has opens "Add a product" with it, which writes what products.add_product writes
// (do=product, pages/lib/55_products.js: the page's alone) and then fills Buy in with the new product.
// A USB or Bluetooth scanner types into the box as a keyboard does, and its Enter sends it; a phone's
// camera does the same through "Scan with camera" (/mealplanner/mealplanner-camera.js, pages/files/),
// which shows only where that file is installed and the browser runs it. A barcode no product has is looked
// up on Open Food Facts from the browser (/mealplanner/mealplanner-lookup.js), which fills in the name and
// what one package holds, never the food; a package size kept from there is sourced there (source=off).
// The food boxes search the names they take as you type (/mealplanner/mealplanner-foods.js), and offer the
// foods a looked-up product likely is, to tap; without it, each keeps its datalist.

const said = runBooking(Object.assign({}, PANTRY_ACTIONS, PRODUCT_ACTIONS));

const options = (values, chosen) => values.map((v) => "<option" + (v === chosen ? " selected" : "") + ">" + esc(v) + "</option>").join("");
const hidden = (fields) => Object.keys(fields).map((k) => "<input type=\"hidden\" name=\"" + k + "\" value=\"" + esc(fields[k]) + "\">").join("");
function form(action, fields, inner, label, confirmText) {
  return "<form class=\"inline\" action=\"/structr/html/pantry\"" + (confirmText ? " onsubmit=\"" + esc("return confirm(" + JSON.stringify(confirmText) + ")") + "\"" : "") + ">"
    + hidden(Object.assign({do: action, token: newToken()}, fields)) + inner + "<button>" + esc(label) + "</button></form>";
}
const amountInputs = (unit, amount, placeholder) => "<input name=\"amount\" type=\"number\" step=\"any\" min=\"0\" required size=\"5\" placeholder=\""
  + esc(placeholder || "amount") + "\"" + (amount != null ? " value=\"" + esc(amount) + "\"" : "") + ">"
  + "<select name=\"unit\">" + options(UNITS, unit) + "</select>";
const given = (v) => v == null ? "" : String(v);

const rows = [];
for (const portion of $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))) {
  const level = onHand(portion);
  if (level == null) continue;                                      // no weighing yet: not known to exist
  if (Array.isArray(level) && level[0] < USED_UP_G) continue;      // used up
  const [days, why] = daysUntilExpiry(portion);
  rows.push({portion: portion, food: portion.instanceOf ? portion.instanceOf.name : portion.name, level: level, days: days, why: why});
}
rows.sort((a, b) => (a.days == null) - (b.days == null) || (a.days - b.days) || a.food.localeCompare(b.food));

const typesIn = (hierarchy) => (($.find("TypeHierarchy", {name: hierarchy})[0] || {}).domainTypes || []);
// products.product_ids: the Types a GTIN denotes, each a packaged product below the food it is a kind of
const products = productIds();
// products.buyable: a food nothing but products sits under (a food others sit under is a group), and each product
const buyable = typesIn("Food Identity").filter((t) => (t.children || []).every((c) => products[c.id]));
const foods = buyable.map((t) => t.name).sort();
// products.buy_unit: the unit Buy picks once a food is chosen: a product's own package size, else the first
// size the food (or its nearest ancestor food) is sold in at the package level, that Buy offers and that
// converts to grams for it; else grams (left out here: the form's own default)
const packageLevel = defaultPackageLevel(), packages = packageLevel ? packageTable(packageLevel) : null;
const buyUnits = {};
for (const t of buyable) {
  const own = resolveDefault(t, PACKAGE_KIND, []);
  const units = (own && own.hasValue ? [own.hasValue.unit] : []).concat(packages ? foodPackages(packages, t).map((p) => p.unit) : []);
  const unit = units.find((u) => UNITS.indexOf(u) >= 0 && toGrams(t, 1, u) != null);
  if (unit && unit !== "g") buyUnits[t.name] = unit;
}
const classes = typesIn("Perishability Class").map((t) => t.name).sort();
// what a product may be a kind of (products.import_products): a food Buy offers that is no product itself
const productFoods = buyable.filter((t) => !products[t.id]).map((t) => t.name).sort();

// The barcode scanned or typed (?scan=), else the one a product was just added with: what it names
const added = BOOKED && BOOKED.action === "product" && !BOOKED.problem;
const asked = given($.request.scan).trim() || (added ? given($.request.barcode).trim() : "");
let scan = null;
if (asked) {
  try {
    scan = findProduct(asked);
  } catch (e) {
    if (!(e instanceof BookingError)) throw e;
    scan = {problem: e.message};
  }
}
// a scan led here: the barcode box keeps the cursor for the next one, unless a product is to be named first
const scanning = !!(asked || $.request.scanning);
let fill = {food: "", amount: null, unit: "g"};      // Buy, filled in with the product scanned
let scanSaid = "";
if (scan && scan.problem) scanSaid = "<p class=\"problem\">Problem: " + esc(scan.problem) + "</p>";
else if (scan && scan.product) {
  fill = {food: scan.product, amount: scan.amount, unit: scan.unit || "g"};
  if (scan.amount != null && UNITS.indexOf(fill.unit) < 0) {          // a unit Buy does not offer: its grams
    fill = {food: scan.product, amount: toGrams(typeNamed(scan.product), scan.amount, scan.unit), unit: "g"};
  }
  scanSaid = "<p class=\"scanned\">" + esc(scan.product) + (scan.food ? " <small>(" + esc(scan.food) + ")</small>" : "")
    + (scan.amount != null ? ": one package holds " + esc(number(scan.amount, 2)) + " " + esc(scan.unit)
       + ". Change the amount for more than one package, and Add to pantry."
       : ": no package size is known for it, so give the amount.") + "</p>";
}
// "Add a product": open with the barcode scanned where no product has it, or with what was sent where adding failed
const retry = BOOKED && BOOKED.action === "product" && BOOKED.problem;
const unknown = scan && !scan.problem && !scan.product;
const draft = retry ? {barcode: given($.request.barcode), name: given($.request.name), food: given($.request.food),
                       amount: given($.request.amount) || null, unit: given($.request.unit) || "g",
                       source: $.request.source === "off" ? "off" : ""}
  : {barcode: unknown ? asked : "", name: "", food: "", amount: null, unit: "g", source: ""};
if (unknown) scanSaid = "<p class=\"note\">No product has barcode " + esc(asked) + " yet: add it below, "
  + "or buy its food by name.</p>";

// A file tools/install_pages.py put in the /mealplanner/ folder: its address, changed whenever its content is,
// so a browser does not keep an old copy; null where it is not installed
function servedFile(name) {
  const file = $.find("File", {name: name}).filter((f) => f.path === "/mealplanner/" + name)[0];
  if (!file) return null;
  const stamp = file.lastModifiedDate ? new Date(file.lastModifiedDate).getTime() : 0;
  return file.path + "?v=" + (file.checksum || stamp);
}
const cameraScript = servedFile(CAMERA_FILE), barcodeReader = servedFile(READER_FILE), lookupScript = servedFile(LOOKUP_FILE);
// the food picker, before the look-up that offers it the foods a product likely is
const foodsScript = servedFile(FOODS_FILE);
const picker = foodsScript ? "<script src=\"" + esc(foodsScript) + "\" defer></script>" : "";
// the barcode to look up on Open Food Facts, where no product has it and the look-up is installed
const lookup = !lookupScript ? "" : (unknown ? "<p class=\"lookup note\" data-lookup=\"" + esc(scan.gtin) + "\" hidden></p>" : "")
  + "<script src=\"" + esc(lookupScript) + "\" defer></script>";
const camera = cameraScript && barcodeReader
  ? "<button type=\"button\" class=\"camera\" hidden data-reader=\"" + esc(barcodeReader) + "\">Scan with camera</button>" : "";
const cameraPanel = !camera ? "" : "<div id=\"camera\" class=\"camera\" hidden><video playsinline muted hidden></video>"
  + "<p class=\"camera-note note\"></p><label class=\"camera-photo\" hidden>Photo of the barcode "
  + "<input type=\"file\" accept=\"image/*\" capture=\"environment\"></label> <button type=\"button\" class=\"camera-stop\">Close</button></div>"
  + "<script src=\"" + esc(cameraScript) + "\" defer></script>";

let html = nav("pantry") + "<h1>Pantry</h1>" + said
  + "<details class=\"buy\" open><summary>Buy</summary>"
  + "<form class=\"inline scan\" action=\"/structr/html/pantry\"><input name=\"scan\" inputmode=\"numeric\" autocomplete=\"off\""
  + " required size=\"16\" placeholder=\"scan or type a barcode\"" + (scanning && !unknown ? " autofocus" : "") + "><button>Look up</button>"
  + camera + "</form>" + cameraPanel
  + scanSaid
  + form("buy", scan && scan.product ? {scanning: "1"} : {}, "<input name=\"food\" list=\"foods\" required placeholder=\"food\" size=\"24\""
    + (fill.food ? " value=\"" + esc(fill.food) + "\"" : "") + ">" + amountInputs(fill.unit, fill.amount)
    + "<select name=\"storage\">" + options(STORAGE, "Fridge") + "</select>"
    + "<select name=\"keeps\" title=\"For a food FoodKeeper gives no time for\"><option value=\"\">keeps as FoodKeeper says</option>"
    + options(classes) + "</select>", "Add to pantry")
  + "<datalist id=\"foods\">" + foods.map((f) => "<option value=\"" + esc(f) + "\">").join("") + "</datalist></details>"
  + "<details class=\"product\"" + (unknown || retry ? " open" : "") + "><summary>Add a product</summary>"
  + "<p class=\"note\">A product is a packaged food with a barcode, bought as many packages of what one holds. It is "
  + "stock of its food, and keeps and weighs as that food does. A package of another size is another product.</p>"
  + picker + lookup
  + form("product", {scanning: "1", source: draft.source}, "<input name=\"barcode\" inputmode=\"numeric\" autocomplete=\"off\" required size=\"16\" placeholder=\"barcode\""
    + (draft.barcode ? " value=\"" + esc(draft.barcode) + "\"" : "") + ">"
    + "<input name=\"name\" required size=\"24\" placeholder=\"name, as on the package\"" + (draft.name ? " value=\"" + esc(draft.name) + "\"" : "")
    + (unknown ? " autofocus" : "") + ">"
    + "<input name=\"food\" list=\"product-foods\" required size=\"24\" placeholder=\"the food it is\""
    + (draft.food ? " value=\"" + esc(draft.food) + "\"" : "") + ">"
    + amountInputs(draft.unit, draft.amount, "one holds"), "Add product")
  + "<datalist id=\"product-foods\">" + productFoods.map((f) => "<option value=\"" + esc(f) + "\">").join("") + "</datalist></details>"
  + "<p class=\"note\">" + rows.length + " foods on hand, " + rows.filter((r) => r.days != null).length
  + " with a known shelf life. Soonest to expire first.</p>"
  + "<table><thead><tr><th>Food</th><th>On hand</th><th>Weighed</th><th>Expires (estimate)</th><th></th></tr></thead><tbody>";
const data = [];
for (const r of rows) {
  const told = Array.isArray(r.level);
  const grams = told ? r.level[0] : null;
  data.push({portion: r.portion.name, grams: grams, days: r.days});
  const expires = r.days == null ? "<span class=\"note\">unknown: " + esc(r.why) + "</span>"
    : (r.days < 0 ? "<span class=\"above_max\">expired " + number(-r.days, 0) + " days ago</span>"
      : esc(dayLabel(new Date(NOW.getTime() + r.days * 86400e3), "UTC")) + " <small>(" + number(r.days, 0) + " days; " + esc(r.why) + ")</small>");
  const id = {portion: r.portion.id};
  const box = r.portion.locatedIn;
  const kept = (box && box.hasStorageCondition && box.hasStorageCondition.name) || "Fridge";
  const opened = box && box.hasOpenedStatus && box.hasOpenedStatus.name === "Opened";
  const actions = r.portion.type !== "PortionOfSubstance" ? "" : "<details><summary>Change</summary>"
    + form("use", id, amountInputs("g"), "Use") + form("count", id, amountInputs("g"), "Count")
    + (opened ? "" : form("open", id, "", "Open"))
    + form("move", Object.assign({storage: kept === "Freezer" ? "Fridge" : "Freezer"}, id), "", kept === "Freezer" ? "Move to fridge" : "Freeze")
    + form("discard", id, "", "Discard", "Throw away all of " + r.food + "?") + "</details>";
  html += "<tr><td>" + esc(r.food) + (opened ? " <small>(opened)</small>" : "") + "</td><td class=\"num\">"
    + (told ? number(grams, 0) + " g" : "<span class=\"note\">" + esc(r.level) + "</span>")
    + "</td><td>" + (told ? esc(dayLabel(r.level[2], "UTC")) + " <small>(" + esc(r.level[1].status) + ")</small>" : "") + "</td><td>" + expires
    + "</td><td>" + actions + "</td></tr>";
}
html += "</tbody></table><p class=\"note\">Imputed: an amount from the pantry profile, not a weighing. An expiry is an "
  + "estimate: the shelf life for how a portion is kept now, opened or sealed, counted from when it was bought or first weighed. "
  + "When it was opened, frozen or moved is not recorded, so freezing keeps a portion's shelf life as if it had always been "
  + "frozen, and opening one judges it as if opened from the start (storage is a tag, not a history: docs/pantry.md).</p>";
// choosing a food Buy offers sets the unit to the one it picks for it (buyUnits); typing part of a name changes nothing
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>"
  + "<script type=\"application/json\" id=\"buy-data\">" + JSON.stringify(foods).replace(/</g, "\\u003c") + "</script>"
  + "<script type=\"application/json\" id=\"buy-units\">" + JSON.stringify(buyUnits).replace(/</g, "\\u003c") + "</script>"
  + "<script type=\"application/json\" id=\"scan-data\">" + JSON.stringify(scan).replace(/</g, "\\u003c") + "</script>"
  + "<script>(function () { var food = document.querySelector('details.buy input[name=food]'); if (!food) return;"
  + " var unit = food.form.querySelector('select[name=unit]');"
  + " var offered = JSON.parse(document.getElementById('buy-data').textContent), units = JSON.parse(document.getElementById('buy-units').textContent);"
  + " function pick() { var name = food.value.trim(); if (offered.indexOf(name) >= 0) unit.value = units[name] || 'g'; }"
  + " food.addEventListener('input', pick); food.addEventListener('change', pick); })();</script>");
