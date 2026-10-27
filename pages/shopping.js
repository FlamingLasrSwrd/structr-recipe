// /structr/html/shopping[/<MealPlan id>][?prices=<price level>]: a committed week's shopping list, as
// mealplanner/shopping.py makes it: what the week's committed, not yet cooked meals call for (scaled by
// servings planned over the recipe's yield), less eligible stock on hand, by the day each food is first
// needed, with a cost at a price level. Stock policies' target levels are not applied here (the owner
// has none, 2026-10-23); with one in the graph the page says so, and tools/shopping_list.py applies it.
// The list itself is pages/lib/90_shopping.js (shoppingFor), which the shoppingList method returns.

const GRAMS_PER_LB = 453.592, GRAMS_PER_OZ = 28.3495;

// shopping.Line.amount
function amountText(grams, each) {
  if (each) return Math.ceil(grams / each - 1e-9) + " (about " + number(grams, 0) + " g)";
  if (grams >= GRAMS_PER_LB / 2) return number(grams, 0) + " g (" + (grams / GRAMS_PER_LB).toFixed(1) + " lb)";
  if (grams >= GRAMS_PER_OZ) return number(grams, 0) + " g (" + (grams / GRAMS_PER_OZ).toFixed(1) + " oz)";
  return number(grams, 0) + " g";
}

const week = chosenWeek();
const levelName = $.request.prices || "Home prices";
let html = nav("shopping") + "<h1>Shopping list</h1>";
const data = {to_buy: [], covered: [], unquantified: {}, not_bought: [], unpriced: []};
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const list = shoppingFor(week, levelName, false);
  const zone = list.zone, table = list.priced, n = {cooks: list.cooks, leftovers: list.leftovers, unquantified: list.unquantified};
  const buy = list.buy, covered = list.covered;
  data.not_bought = list.not_bought;
  data.unpriced = list.unpriced;
  const total = list.total;
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("shopping", week)
    + "<p class=\"note\">" + n.cooks + " meals to cook, " + n.leftovers + " of leftovers (which need nothing more). What the meals call for, "
    + "less what the pantry holds; amounts are what the recipes use, not package sizes. Tick items off as you go; the ticks stay in this browser.</p>";
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
      + "<td class=\"num\">" + esc(amountText(l.buy, l.each)) + "</td>"
      + "<td class=\"num" + (l.estimated ? " estimated" : "") + "\">" + (l.cost == null ? "" : "$" + l.cost.toFixed(2)) + "</td>"
      + "<td class=\"note\">" + (l.have > 0 ? "have " + number(l.have, 0) + " g of " + number(l.need, 0) + " g; " : "") + esc(l.recipes.join(", ")) + "</td></tr>";
    data.to_buy.push({food: l.food, buy: l.buy, need: l.need, have: l.have, first: l.first ? l.first.toISOString() : null, cost: l.cost});
  }
  html += day === null ? "<p>Nothing to buy: the pantry covers the week.</p>" : "</tbody></table>";
  if (table) html += "<p><b>About $" + total.toFixed(2) + "</b> at " + esc(levelName) + (buy.some((l) => l.estimated) ? " (italics: priced from an estimate)" : "")
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
