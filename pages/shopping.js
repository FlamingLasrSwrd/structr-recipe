// /structr/html/shopping[/<MealPlan id>][?prices=<price level>][&packages=<package level>]: a committed
// week's shopping list, as mealplanner/shopping.py makes it: what the week's committed, not yet cooked
// meals call for (scaled by servings planned over the recipe's yield), less eligible stock on hand, by
// the day each food is first needed, rounded up to what each food is sold in (by default at "Home
// packages" where there is one, else "US supermarket"), with what will be left and until when, and a
// cost at a price level. Stock policies' target levels are not applied here (the owner
// has none, 2026-10-23); with one in the graph the page says so, and tools/shopping_list.py applies it.
// The list itself is pages/lib/90_shopping.js (shoppingFor), which the shoppingList method returns.
//
// Ticking a line and "Put ticked items into the pantry" books what the line buys as a purchase (docs/pantry.md,
// "Ticking the shopping list"): its whole packages, each a portion of its own, kept where storageFor says, or the
// line as changed before (a product of its food, how many packages, other grams, where it is kept). One form sends
// every ticked line, each booked on its own (PANTRY_ACTIONS.bought, pantry.buy_line) with a token of its own, the
// form's and the line's number, so a form sent twice books nothing twice. The ticks are kept in the browser until
// then, so a list can be ticked in the shop without a connection. A purchase booked from here can be taken back
// (do=unbuy, pantry.unbuy) while nothing has drawn on it: right after, and later from the browser that booked it.

const GRAMS_PER_LB = 453.592, GRAMS_PER_OZ = 28.3495;

// shopping._grams_text
function gramsText(grams) {
  if (grams >= GRAMS_PER_LB / 2) return number(grams, 0) + " g (" + (grams / GRAMS_PER_LB).toFixed(1) + " lb)";
  if (grams >= GRAMS_PER_OZ) return number(grams, 0) + " g (" + (grams / GRAMS_PER_OZ).toFixed(1) + " oz)";
  return number(grams, 0) + " g";
}

// shopping.Line.amount
function amountText(line) {
  if (line.packages.length) return line.packages.map((p) => p.count + " \u00d7 " + p.label).join(" + ") + " (about " + number(line.as_bought != null ? line.as_bought : line.bought, 0) + " g)";
  if (line.each) return Math.ceil(line.buy / line.each - 1e-9) + " (about " + number(line.bought || line.buy, 0) + " g)";
  if (line.as_bought != null && line.edible < 1) return gramsText(line.as_bought) + " as bought";
  return gramsText(line.buy);
}

// shopping.describe's notes on a purchased form: what a line is bought to make, and what of it is used
function formText(line) {
  const out = [];
  if (line.made.length) out.push("for " + line.made.map((m) => m[0] + " (" + number(m[1], 0) + " g)").join(", "));
  if (line.edible < 1 && !(line.each && !line.packages.length)) {
    out.push(Math.round(line.edible * 100) + "% of it as bought is used" + (line.trimmed ? " (less " + line.trimmed + ")" : ""));
  }
  return out.join("; ");
}

// shopping.left_over_text
const dateLabel = (d, zone) => new Intl.DateTimeFormat("en-US", {timeZone: zone, weekday: "short", month: "short", day: "numeric", year: "numeric"}).format(d);
function leftText(line, zone) {
  if (line.left < LEFT_G) return "";
  return gramsText(line.left) + " left over" + (line.left_cost == null ? "" : " ($" + line.left_cost.toFixed(2) + ")")
    + (line.keeps_until ? ", keeps to " + dateLabel(line.keeps_until, zone) + (line.keeps_opened ? " once opened" : " unopened") : ", no shelf life known");
}

const week = chosenWeek();
// "Put ticked items into the pantry": each ticked line (t<i>) booked on its own, with the form's token and the line's
// number; or a purchase taken back (do=unbuy). What it says, and what it booked, for the browser and the checks.
function runShopping() {
  const action = $.request.do, out = {html: "", booked: [], undone: null};
  if (action !== "bought" && action !== "unbuy") return out;
  const token = String($.request.token || "");
  // a line's token is the form's and three hex digits of its number, within the 16 a booking takes
  if (!/^[0-9a-f]{4,16}$/.test(token) || (action === "bought" && token.length > 13)) {
    out.html = "<p class=\"problem\">Problem: the form had no token; reload the page and try again.</p>";
    return out;
  }
  const whose = bookingHousehold(action);
  if (whose.refused) {
    out.html = "<p class=\"problem\">Problem: " + esc(whose.refused) + ".</p>";
    return out;
  }
  const records = [];
  if (action === "unbuy") {
    const done = bookFromPage(PANTRY_ACTIONS, "unbuy", $.request, token, whose);
    records.push(bookingRecord("unbuy", done, whose));
    out.undone = String($.request.purchase || "");
    out.html = done.problem ? "<p class=\"problem\">Problem: " + esc(done.problem) + "</p>"
      : "<p class=\"booked\">" + esc(done.booking.process) + " taken back: no longer in the pantry, so it is on the list again.</p>";
  } else {
    const count = Math.min(Number($.request.lines) || 0, 999), said = [];
    for (let i = 0; i < count; i++) {
      if (!$.request["t" + i]) continue;
      const asked = {};
      for (const key of ["food", "pieces", "buy", "product", "count", "grams", "storage"]) asked[key] = $.request[key + i];
      const lineToken = token + ("00" + i.toString(16)).slice(-3);
      const done = bookFromPage(PANTRY_ACTIONS, "bought", asked, lineToken, whose);
      records.push(Object.assign({line: i, food: String(asked.food || "")}, bookingRecord("bought", done, whose)));
      if (done.problem) {
        said.push("<p class=\"problem\">Problem: " + esc(done.problem) + "</p>");
        continue;
      }
      out.booked.push({item: (week ? week.id : "") + "|" + String(asked.food || ""), food: String(asked.food || ""), purchase: lineToken});
      said.push("<div class=\"booked\">" + esc(done.booking.notes.join("; ") + ".") + (done.booking.created.length ? "" : " (put in before, so nothing new was written)")
        + " " + undoForm(lineToken) + "</div>");
    }
    out.html = said.length ? said.join("") : "<p class=\"problem\">Problem: nothing was ticked.</p>";
  }
  out.html += "<script type=\"application/json\" id=\"booking-data\">" + JSON.stringify({action: action, bookings: records}).replace(/</g, "\\u003c")
    + "</script><script>history.replaceState(null, '', " + JSON.stringify(pagePath() + levelQuery()).replace(/</g, "\\u003c") + ");</script>";
  return out;
}

// A form taking back the purchase of this token
function undoForm(purchase) {
  return "<form class=\"inline\" action=\"" + esc(pagePath()) + "\">" + "<input type=\"hidden\" name=\"do\" value=\"unbuy\">"
    + "<input type=\"hidden\" name=\"purchase\" value=\"" + esc(purchase) + "\">" + keptLevels()
    + "<input type=\"hidden\" name=\"token\" value=\"" + newToken() + "\"><button>Undo</button></form>";
}

// This page's address for the week shown, and the levels it was asked for, as hidden fields
const pagePath = () => "/structr/html/shopping" + (week ? "/" + week.id : "");
const levelQuery = () => {
  const asked = ["prices", "packages"].filter((k) => $.request[k]);
  return asked.length ? "?" + asked.map((k) => k + "=" + encodeURIComponent(String($.request[k]))).join("&") : "";
};
const keptLevels = () => ["prices", "packages"].filter((k) => $.request[k])
  .map((k) => "<input type=\"hidden\" name=\"" + k + "\" value=\"" + esc($.request[k]) + "\">").join("");

// The products of a food a line could be bought as instead: those below it with a package size, by name
let productIdsRead = null;
function productsOf(foodName) {
  const food = $.find("DomainType", {name: foodName}).filter((t) => t.type === "DomainType")[0];
  if (!food) return {food: null, products: []};
  const ids = productIdsRead || (productIdsRead = productIds());
  return {food: food, products: (food.children || []).filter((c) => ids[c.id]).filter((c) => {
    const size = resolveDefault(c, PACKAGE_KIND, []);
    return size && size.hasValue && toGrams(c, size.hasValue.value, size.hasValue.unit) > 0;
  }).map((c) => c.name).sort()};
}

const shopping = runShopping();
const levelName = $.request.prices || "Home prices";
const packageLevel = $.request.packages || defaultPackageLevel();
let html = nav("shopping") + "<h1>Shopping list</h1>" + shopping.html;
const data = {to_buy: [], covered: [], unquantified: {}, not_bought: [], unpriced: []};
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const list = shoppingFor(week, levelName, false, packageLevel);
  const zone = list.zone, table = list.priced, n = {cooks: list.cooks, leftovers: list.leftovers, unquantified: list.unquantified};
  const buy = list.buy, covered = list.covered;
  data.not_bought = list.not_bought;
  data.unpriced = list.unpriced;
  const total = list.total;
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("shopping", week)
    + "<p class=\"note\">" + n.cooks + " meals to cook, " + n.leftovers + " of leftovers (which need nothing more). What the meals call for, "
    + "less what the pantry holds; " + (list.packaged ? "rounded up to what is sold at " + esc(packageLevel) + " (italics: a size rests on an estimate)"
                                                      : "amounts are what the recipes use, not package sizes" + (packageLevel ? " (no package level named " + esc(packageLevel) + ")" : ""))
    + ". Tick items off as you go (the ticks stay in this browser), then put them into the pantry: each line's packages "
    + "go in as they are listed, unless you change the line first.</p>";
  if ($.find("StockPolicy").length) html += "<p class=\"note\">Stock policies are not applied on this page: <code>tools/shopping_list.py</code> adds their levels.</p>";
  const putAway = "<p><button class=\"put-away\">Put ticked items into the pantry</button></p>";
  if (buy.length) html += "<form class=\"bought\" action=\"" + esc(pagePath()) + "\">" + "<input type=\"hidden\" name=\"do\" value=\"bought\">"
    + "<input type=\"hidden\" name=\"token\" value=\"" + newToken() + "\"><input type=\"hidden\" name=\"lines\" value=\"" + buy.length + "\">"
    + keptLevels() + putAway;
  let day = null, index = 0;
  for (const l of buy) {
    const key = l.first ? dayKey(l.first, zone) : "none";
    if (key !== day) {
      html += (day === null ? "" : "</tbody></table>") + "<h3>First needed " + (l.first ? esc(dayLabel(l.first, zone)) : "on no set day") + "</h3>"
        + "<table class=\"shopping\"><tbody>";
      day = key;
    }
    const id = "item-" + esc(l.food).replace(/[^A-Za-z0-9]/g, "-"), i = index++;
    const choice = productsOf(l.food);
    const field = (name, value) => "<input type=\"hidden\" name=\"" + name + i + "\" value=\"" + esc(value) + "\">";
    // what the line puts in the pantry unless changed: its packages as a recipe weighs them, a product of its food
    // instead, other grams, or another place
    const change = "<details class=\"change\"><summary>Change</summary><div class=\"line-change\">"
      + (choice.products.length ? "<label>Bought <select name=\"product" + i + "\"><option value=\"\">" + esc(l.food) + ", as listed</option>"
         + choice.products.map((p) => "<option>" + esc(p) + "</option>").join("") + "</select></label>"
         + "<label><input name=\"count" + i + "\" type=\"number\" min=\"1\" step=\"1\" placeholder=\"how many\"> packages of it</label>" : "")
      + "<label>or <input name=\"grams" + i + "\" type=\"number\" min=\"0\" step=\"any\" placeholder=\"grams\"> g in all</label>"
      + "<label>Kept in <select name=\"storage" + i + "\"><option value=\"\">the " + esc(choice.food ? storageFor(choice.food).toLowerCase() : "fridge")
      + " (where it keeps)</option>" + STORAGE.map((w) => "<option>" + w + "</option>").join("") + "</select></label></div></details>";
    html += "<tr><td><input type=\"checkbox\" name=\"t" + i + "\" value=\"1\" id=\"" + id + "\" data-item=\"" + esc(week.id + "|" + l.food) + "\">"
      + field("food", l.food) + field("pieces", l.pieces.map((g) => Math.round(g * 1e6) / 1e6).join(",")) + field("buy", Math.round(l.buy * 1e6) / 1e6) + "</td>"
      + "<td><label for=\"" + id + "\">" + esc(l.food) + (l.optional ? " <i>(optional)</i>" : "") + "</label>" + change + "</td>"
      + "<td class=\"num" + (l.estimated_size ? " estimated" : "") + "\">" + esc(amountText(l)) + "</td>"
      + "<td class=\"num" + (l.estimated ? " estimated" : "") + "\">" + (l.cost == null ? "" : "$" + l.cost.toFixed(2)) + "</td>"
      + "<td class=\"note\">" + (l.have > 0 ? "have " + number(l.have, 0) + " g of " + number(l.need, 0) + " g; " : "")
      + (formText(l) ? esc(formText(l)) + "; " : "") + esc(l.recipes.join(", "))
      + (leftText(l, zone) ? "<br>" + esc(leftText(l, zone)) : "") + "</td></tr>";
    data.to_buy.push({food: l.food, buy: l.buy, need: l.need, have: l.have, first: l.first ? l.first.toISOString() : null, cost: l.cost,
                      packages: l.packages, bought: l.bought, left: l.left, left_cost: l.left_cost, as_bought: l.as_bought, made: l.made,
                      keeps_until: l.keeps_until ? l.keeps_until.toISOString() : null, keeps_opened: l.keeps_opened, pieces: l.pieces});
  }
  html += day === null ? "<p>Nothing to buy: the pantry covers the week.</p>" : "</tbody></table>" + putAway + "</form>";
  html += "<div id=\"bought-here\" hidden><h3>Put in the pantry from this list, on this device</h3><div class=\"rows\"></div></div>";
  if (table) html += "<p><b>About $" + total.toFixed(2) + "</b> at " + esc(levelName)
    + (list.left_total >= 0.005 ? ", of which $" + list.left_total.toFixed(2) + " is left over" : "")
    + (buy.some((l) => l.estimated) ? " (italics: priced from an estimate)" : "")
    + (data.unpriced.length ? "; not priced: " + esc(data.unpriced.sort().join(", ")) : "") + ".</p>";
  else html += "<p class=\"note\">No price level named " + esc(levelName) + ": add <code>?prices=</code> with one.</p>";
  if (data.not_bought.length) html += "<p class=\"note\">Not bought: " + esc(data.not_bought.sort().join(", ")) + ".</p>";
  if (covered.length) html += "<p class=\"note\">The pantry covers: " + covered.map((l) => esc(l.food) + " (" + number(l.need, 0) + " of " + number(l.have, 0) + " g)").join(", ") + ".</p>";
  const loose = Object.keys(n.unquantified).sort();
  if (loose.length) html += "<p class=\"note\">No amount in the recipe, so check there is some: " + loose.map((f) => esc(f) + " (" + esc(n.unquantified[f].join(", ")) + ")").join(", ") + ".</p>";
  data.covered = covered.map((l) => ({food: l.food, need: l.need, have: l.have}));
  data.unquantified = n.unquantified;
  // the ticks, kept in this browser until put away; what this browser put away from this week's list, each with an Undo
  // while it can be (a form of its own, its token made here: any 8 hex digits do)
  html += "<script type=\"application/json\" id=\"bought-data\">" + JSON.stringify({week: week.id, path: pagePath(), booked: shopping.booked,
    undone: shopping.undone, levels: ["prices", "packages"].filter((k) => $.request[k]).map((k) => [k, String($.request[k])])}).replace(/</g, "\\u003c") + "</script>"
    + "<script>(function () { var d = JSON.parse(document.getElementById('bought-data').textContent), key = 'shopbought:' + d.week, mine = [];"
    + " function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }"
    + " function set(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }"
    + " try { mine = JSON.parse(get(key) || '[]') || []; } catch (e) { mine = []; }"
    + " d.booked.forEach(function (b) { set('shop:' + b.item, null); if (!mine.some(function (m) { return m.purchase === b.purchase; }))"
    + " mine.push({food: b.food, purchase: b.purchase, at: Date.now()}); });"
    + " mine = mine.filter(function (m) { return m.purchase !== d.undone && Date.now() - (m.at || 0) < 14 * 86400e3; }).slice(-40); set(key, JSON.stringify(mine));"
    + " document.querySelectorAll('input[data-item]').forEach(function (box) { box.checked = get('shop:' + box.dataset.item) === '1';"
    + " box.addEventListener('change', function () { set('shop:' + box.dataset.item, box.checked ? '1' : '0'); box.closest('tr').classList.toggle('done', box.checked); });"
    + " box.closest('tr').classList.toggle('done', box.checked); });"
    + " var form = document.querySelector('form.bought'); if (form) form.addEventListener('submit', function (e) {"
    + " var any = false; form.querySelectorAll('input[data-item]').forEach(function (box) { if (box.checked) { any = true; return; }"
    + " box.closest('tr').querySelectorAll('input, select').forEach(function (f) { f.disabled = true; }); });"
    + " if (!any) { e.preventDefault(); form.querySelectorAll('input, select').forEach(function (f) { f.disabled = false; }); alert('Tick what you bought first.'); } });"
    + " if (!mine.length) return; var here = document.getElementById('bought-here'), rows = here.querySelector('.rows'); here.hidden = false;"
    + " mine.forEach(function (m) { var f = document.createElement('form'); f.className = 'inline'; f.action = d.path;"
    + " var fields = [['do', 'unbuy'], ['purchase', m.purchase], ['token', ('0000000' + Math.floor(Math.random() * 4294967296).toString(16)).slice(-8)]].concat(d.levels);"
    + " fields.forEach(function (kv) { var i = document.createElement('input'); i.type = 'hidden'; i.name = kv[0]; i.value = kv[1]; f.appendChild(i); });"
    + " var s = document.createElement('span'); s.textContent = m.food + ' '; f.appendChild(s);"
    + " var b = document.createElement('button'); b.textContent = 'Undo'; f.appendChild(b); rows.appendChild(f); }); })();</script>";
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
