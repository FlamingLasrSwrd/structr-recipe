// /structr/html/pantry: the stock on hand now and when it expires, soonest first, as mealplanner/inventory.py
// works them out: the latest weighing less every use since (current_magnitude), and the shelf life of
// its perishability where it is kept, from when it was bought or first weighed (instance_expiration).
//
// Its forms book what happens to it, as mealplanner/pantry.py does (docs/pantry.md): buy, use, count
// (a stock take), open, move (freeze) and discard. Each sends ?do=<booking>&token=<one per form>.

const STORAGE = ["Fridge", "Freezer", "Pantry"];
const UNITS = ["g", "kg", "oz", "lb", "ml", "l", "cup", "tbsp", "tsp", "fl_oz", "each"];

// pantry._grams
function bookingGrams(food, amount, unit) {
  if (!(amount > 0)) throw new BookingError(food.name + ": an amount must be more than 0");
  const grams = toGrams(food, amount, unit);
  if (grams == null) throw new BookingError(food.name + ": " + amount + " " + unit + " does not convert to grams (no density or weight per item for it)");
  return grams;
}

function portionFrom(request) {
  const found = $.find("PortionOfSubstance", {id: String(request.portion || "")});
  const portion = Array.isArray(found) ? found[0] : found;
  if (!portion || portion.type !== "PortionOfSubstance") throw new BookingError("no such portion");
  return portion;
}

function amountFrom(request) {
  const amount = Number(request.amount);
  if (request.amount == null || request.amount === "" || isNaN(amount)) throw new BookingError("an amount is a number");
  return amount;
}

// pantry.last_perishability
function lastPerishability(food) {
  let best = null;
  for (const p of $.find("PortionOfSubstance")) {
    if (!p.instanceOf || p.instanceOf.id !== food.id || !p.hasPerishabilityType) continue;
    const key = p.createdDate ? new Date(p.createdDate).toISOString() : "";
    if (!best || key > best[0]) best = [key, p.hasPerishabilityType];
  }
  return best ? best[1] : null;
}

// pantry._container
function containerOf(booking, portion) {
  if (portion.locatedIn) return portion.locatedIn;
  const box = ensureNode(booking, "ContainerObject", portion.name + " container", {
    hasStorageCondition: typeNamed("Fridge"), hasOpenedStatus: typeNamed("Sealed")});
  portion.locatedIn = box;
  return box;
}

const PANTRY_ACTIONS = {
  // pantry.buy
  buy: (booking, r, token) => {
    const storage = String(r.storage || "Fridge");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const food = typeNamed(String(r.food || "").trim());
    const amount = amountFrom(r), unit = String(r.unit || "g");
    bookingGrams(food, amount, unit);
    const keeps = r.keeps ? typeNamed(String(r.keeps)) : lastPerishability(food);
    const sealed = typeNamed("Sealed"), where = typeNamed(storage);
    const process = bookProcess(booking, "Purchase", "Purchase " + token, NOW);
    const name = "Purchase " + token + " -- " + food.name;
    const box = ensureNode(booking, "ContainerObject", name + " container", {
      hasStorageCondition: typeNamed(storage), hasOpenedStatus: typeNamed("Sealed")});
    const portion = ensureNode(booking, "PortionOfSubstance", name, {
      instanceOf: food, beginsToExistDuring: process, locatedIn: box, hasPerishabilityType: keeps});
    const quality = ensureNode(booking, "Quality", name + " mass Quality", {hasKind: typeNamed("Mass"), inheresIn: portion});
    ensureNode(booking, "Measurement", name + " mass bought", {value: amount, unit: unit, status: "observed",
                                                              hasTime: stamp(NOW), isAboutQuality: quality});
    const shelf = resolveDefault(food, "ShelfLife", [where.id, sealed.id]);
    if (!keeps && !(shelf && shelf.hasValue && shelf.hasValue.unit === "days" && shelf.hasValue.value != null)) {
      booking.notes.push(food.name + ": no shelf life known for it in the " + storage.toLowerCase()
                         + ", so no expiry (name a perishability class when buying)");
    }
  },
  // pantry.use
  use: (booking, r, token) => {
    const portion = portionFrom(r), food = portion.instanceOf;
    const grams = bookingGrams(food, amountFrom(r), String(r.unit || "g"));
    const level = onHand(portion);
    if (!Array.isArray(level)) throw new BookingError(portion.name + ": " + (level || "never weighed") + ", so there is nothing to take from it (count it first)");
    if (grams > level[0] + 1e-6) throw new BookingError(portion.name + ": " + number(grams, 0) + " g is more than the " + number(level[0], 0) + " g on hand");
    bookDraw(booking, bookProcess(booking, "Use", "Use " + token, NOW), portion, grams, NOW, portion.name);
  },
  // pantry.discard
  discard: (booking, r, token) => {
    const portion = portionFrom(r);
    const level = onHand(portion);
    if (!Array.isArray(level) || !(level[0] > 0)) throw new BookingError(portion.name + ": nothing on hand to discard");
    bookDraw(booking, bookProcess(booking, "Discarding", "Discard " + token, NOW), portion, level[0], NOW, portion.name);
  },
  // pantry.stock_take
  count: (booking, r, token) => {
    const portion = portionFrom(r), amount = amountFrom(r), unit = String(r.unit || "g");
    if (amount < 0) throw new BookingError("a stock take is 0 or more");
    if (amount > 0) bookingGrams(portion.instanceOf, amount, unit);
    const quality = massQuality(portion) || ensureNode(booking, "Quality", portion.name + " mass Quality", {
      hasKind: typeNamed("Mass"), inheresIn: portion});
    ensureNode(booking, "Measurement", portion.name + " stock take " + token, {value: amount, unit: unit, status: "observed",
                                                                                hasTime: stamp(NOW), isAboutQuality: quality});
    booking.process = portion.name + " counted";
  },
  // pantry.open_portion
  open: (booking, r) => {
    const portion = portionFrom(r), box = containerOf(booking, portion);
    if (!box.hasOpenedStatus || box.hasOpenedStatus.name !== "Opened") {
      box.hasOpenedStatus = typeNamed("Opened");
      booking.notes.push(portion.name + ": opened.");
    }
  },
  // pantry.move
  move: (booking, r) => {
    const storage = String(r.storage || "");
    if (STORAGE.indexOf(storage) < 0) throw new BookingError("storage must be one of " + STORAGE.join(", "));
    const portion = portionFrom(r), box = containerOf(booking, portion);
    box.hasStorageCondition = typeNamed(storage);
    booking.notes.push(portion.name + ": kept in the " + storage.toLowerCase() + ".");
  },
};

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
  + "<table><thead><tr><th>Food</th><th>On hand</th><th>Weighed</th><th>Expires</th><th></th></tr></thead><tbody>";
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
html += "</tbody></table><p class=\"note\">Imputed: an amount from the pantry profile, not a weighing. Freezing keeps a "
  + "portion's shelf life as if it had always been frozen (storage is a tag, not a history: docs/pantry.md).</p>";
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
