// /structr/html/shopping[/<MealPlan id>][?prices=<price level>][&packages=<package level>]: a committed
// week's shopping list, as mealplanner/shopping.py makes it: what the week's committed, not yet cooked
// meals call for (scaled by servings planned over the recipe's yield), less eligible stock on hand, by
// the day each food is first needed, rounded up to what each food is sold in (by default at "Home
// packages" where there is one, else "US supermarket"), with what will be left and until when, and a
// cost at a price level. Stock policies' target levels are not applied here (the owner
// has none, 2026-10-23); with one in the graph the page says so, and tools/shopping_list.py applies it.
// The list itself is pages/lib/90_shopping.js (shoppingFor), which the shoppingList method returns. Each line
// links to /structr/html/alternatives (pages/alternatives.js): what could take its place, and "bought instead".

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
const levelName = $.request.prices || "Home prices";
const packageLevel = $.request.packages || defaultPackageLevel();
let html = nav("shopping") + "<h1>Shopping list</h1>";
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
    + ". Tick items off as you go; the ticks stay in this browser.</p>";
  if ($.find("StockPolicy").length) html += "<p class=\"note\">Stock policies are not applied on this page: <code>tools/shopping_list.py</code> adds their levels.</p>";
  let day = null;
  for (const l of buy) {
    const key = l.first ? dayKey(l.first, zone) : "none";
    if (key !== day) {
      html += (day === null ? "" : "</tbody></table>") + "<h3>First needed " + (l.first ? esc(dayLabel(l.first, zone)) : "on no set day") + "</h3>"
        + "<table class=\"shopping\"><tbody>";
      day = key;
    }
    const id = "item-" + esc(l.food).replace(/[^A-Za-z0-9]/g, "-");
    html += "<tr><td><input type=\"checkbox\" id=\"" + id + "\" data-item=\"" + esc(week.id + "|" + l.food) + "\"></td>"
      + "<td><label for=\"" + id + "\">" + esc(l.food) + (l.optional ? " <i>(optional)</i>" : "") + "</label></td>"
      + "<td class=\"num" + (l.estimated_size ? " estimated" : "") + "\">" + esc(amountText(l)) + "</td>"
      + "<td class=\"num" + (l.estimated ? " estimated" : "") + "\">" + (l.cost == null ? "" : "$" + l.cost.toFixed(2)) + "</td>"
      + "<td class=\"note\">" + (l.have > 0 ? "have " + number(l.have, 0) + " g of " + number(l.need, 0) + " g; " : "")
      + (formText(l) ? esc(formText(l)) + "; " : "") + (l.instead.length ? "bought in place of " + esc(l.instead.join(", ")) + "; " : "")
      + esc(l.recipes.join(", "))
      + (leftText(l, zone) ? "<br>" + esc(leftText(l, zone)) : "") + "</td>"
      + "<td><a href=\"/structr/html/alternatives/" + esc(week.id) + "?food=" + encodeURIComponent(l.food) + "\" title=\"What could take its place, "
      + "and buying something else instead\">Alternatives</a></td></tr>";
    data.to_buy.push({food: l.food, buy: l.buy, need: l.need, have: l.have, first: l.first ? l.first.toISOString() : null, cost: l.cost,
                      packages: l.packages, bought: l.bought, left: l.left, left_cost: l.left_cost, as_bought: l.as_bought, made: l.made,
                      keeps_until: l.keeps_until ? l.keeps_until.toISOString() : null, keeps_opened: l.keeps_opened,
                      instead: l.instead});
  }
  html += day === null ? "<p>Nothing to buy: the pantry covers the week.</p>" : "</tbody></table>";
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
  html += "<script>document.querySelectorAll('input[data-item]').forEach(function (box) {"
    + "try { box.checked = localStorage.getItem('shop:' + box.dataset.item) === '1'; } catch (e) {}"
    + "box.addEventListener('change', function () { try { localStorage.setItem('shop:' + box.dataset.item, box.checked ? '1' : '0'); } catch (e) {} "
    + "box.closest('tr').classList.toggle('done', box.checked); });"
    + "box.closest('tr').classList.toggle('done', box.checked); });</script>";
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
