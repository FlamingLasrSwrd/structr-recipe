// /structr/html/pantry: the stock on hand now and when it expires, soonest first, as mealplanner/inventory.py
// works them out: the latest weighing less every use since (current_magnitude), and the shelf life of
// its perishability where it is kept, from when it was bought or first weighed (instance_expiration).
//
// Its forms book what happens to it, as mealplanner/pantry.py does (docs/pantry.md): buy, use, count
// (a stock take), open, move (freeze) and discard. Each sends ?do=<booking>&token=<one per form>.
// The bookings themselves are in pages/common.js (PANTRY_ACTIONS), shared with the bookPantry method.

const said = runBooking(PANTRY_ACTIONS);

const options = (values, chosen) => values.map((v) => "<option" + (v === chosen ? " selected" : "") + ">" + esc(v) + "</option>").join("");
const hidden = (fields) => Object.keys(fields).map((k) => "<input type=\"hidden\" name=\"" + k + "\" value=\"" + esc(fields[k]) + "\">").join("");
function form(action, fields, inner, label, confirmText) {
  return "<form class=\"inline\" action=\"/structr/html/pantry\"" + (confirmText ? " onsubmit=\"return confirm('" + esc(confirmText) + "')\"" : "") + ">"
    + hidden(Object.assign({do: action, token: newToken()}, fields)) + inner + "<button>" + esc(label) + "</button></form>";
}
const amountInputs = (unit) => "<input name=\"amount\" type=\"number\" step=\"any\" min=\"0\" required size=\"5\" placeholder=\"amount\">"
  + "<select name=\"unit\">" + options(UNITS, unit) + "</select>";

const rows = [];
for (const portion of $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))) {
  const level = onHand(portion);
  if (level == null) continue;                                      // no weighing yet: not known to exist
  if (Array.isArray(level) && level[0] <= 1e-9) continue;          // used up
  const [days, why] = daysUntilExpiry(portion);
  rows.push({portion: portion, food: portion.instanceOf ? portion.instanceOf.name : portion.name, level: level, days: days, why: why});
}
rows.sort((a, b) => (a.days == null) - (b.days == null) || (a.days - b.days) || a.food.localeCompare(b.food));

const typesIn = (hierarchy) => (($.find("TypeHierarchy", {name: hierarchy})[0] || {}).domainTypes || []);
const foods = typesIn("Food Identity").filter((t) => !(t.children || []).length).map((t) => t.name).sort();
const classes = typesIn("Perishability Class").map((t) => t.name).sort();

let html = nav("pantry") + "<h1>Pantry</h1>" + said
  + "<details class=\"buy\" open><summary>Buy</summary>"
  + form("buy", {}, "<input name=\"food\" list=\"foods\" required placeholder=\"food\" size=\"24\">" + amountInputs("g")
    + "<select name=\"storage\">" + options(STORAGE, "Fridge") + "</select>"
    + "<select name=\"keeps\" title=\"For a food FoodKeeper gives no time for\"><option value=\"\">keeps as FoodKeeper says</option>"
    + options(classes) + "</select>", "Add to pantry")
  + "<datalist id=\"foods\">" + foods.map((f) => "<option value=\"" + esc(f) + "\">").join("") + "</datalist></details>"
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
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
