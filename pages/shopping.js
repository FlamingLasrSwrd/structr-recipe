// /structr/html/shopping[/<MealPlan id>][?prices=<price level>][&packages=<package level>]: a committed
// week's shopping list, as mealplanner/shopping.py makes it: what the week's committed, not yet cooked
// meals call for (scaled by servings planned over the recipe's yield), less eligible stock on hand, by
// the day each food is first needed, rounded up to what each food is sold in (by default at "Home
// packages" where there is one, else "US supermarket"), with what will be left and until when, and a
// cost at a price level. Stock policies' target levels are not applied here (the owner
// has none, 2026-10-23); with one in the graph the page says so, and tools/shopping_list.py applies it.
// The list itself is pages/lib/90_shopping.js (shoppingFor), which the shoppingList method returns.

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
    out.push(Math.round(line.edible * 100) + "% of it is used" + (line.trimmed ? " (the rest is " + line.trimmed + ")" : ""));
  }
  return out.join("; ");
}

// shopping.left_over_text
const dateLabel = (d, zone) => new Intl.DateTimeFormat("en-US", {timeZone: zone, weekday: "short", month: "short", day: "numeric", year: "numeric"}).format(d);
function leftText(line, zone) {
  if (line.left < LEFT_G) return "";
  return gramsText(line.left) + " left over" + (line.left_cost == null ? "" : " ($" + line.left_cost.toFixed(2) + ")")
    + (line.keeps_until ? ", keeps until " + dateLabel(line.keeps_until, zone) + (line.keeps_opened ? " once opened" : " unopened") : ", use-by not known");
}

const week = chosenWeek();
const levelName = $.request.prices || "Home prices";
const packageLevel = $.request.packages || defaultPackageLevel();
let html = nav("shopping") + "<h1>Shopping list</h1>";
const data = {to_buy: [], covered: [], unquantified: {}, not_bought: [], unpriced: []};
if (!week) {
  html += "<p>No week is planned yet. To plan one, run <code>tools/plan_week.py</code> with <code>--commit</code>.</p>";
} else {
  const list = shoppingFor(week, levelName, false, packageLevel);
  const zone = list.zone, table = list.priced, n = {cooks: list.cooks, leftovers: list.leftovers, unquantified: list.unquantified};
  const buy = list.buy, covered = list.covered;
  data.not_bought = list.not_bought;
  data.unpriced = list.unpriced;
  const total = list.total;
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("shopping", week)
    + "<p class=\"note\">" + n.cooks + " meal" + (n.cooks === 1 ? "" : "s") + " to cook and " + n.leftovers + " of leftovers. "
    + "This is what those meals need, less what is in the pantry already, "
    + (list.packaged ? "rounded up to whole packages (" + esc(packageLevel) + "). Package sizes in italics are estimates"
                     : "in the amounts the recipes use, not in packages" + (packageLevel ? " (there are no package sizes called " + esc(packageLevel) + ")" : ""))
    + ". Tick items off as you shop; the ticks are kept in this browser only.</p>";
  if ($.find("StockPolicy").length) html += "<p class=\"note\">Foods you keep a stock of are not topped up on this list. "
    + "<code>tools/shopping_list.py</code> adds them.</p>";
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
      + "<td class=\"note\">" + (l.have > 0 ? "have " + number(l.have, 0) + " g of the " + number(l.need, 0) + " g needed; " : "")
      + (formText(l) ? esc(formText(l)) + "; " : "") + esc(l.recipes.join(", "))
      + (leftText(l, zone) ? "<br>" + esc(leftText(l, zone)) : "") + "</td></tr>";
    data.to_buy.push({food: l.food, buy: l.buy, need: l.need, have: l.have, first: l.first ? l.first.toISOString() : null, cost: l.cost,
                      packages: l.packages, bought: l.bought, left: l.left, left_cost: l.left_cost, as_bought: l.as_bought, made: l.made,
                      keeps_until: l.keeps_until ? l.keeps_until.toISOString() : null, keeps_opened: l.keeps_opened});
  }
  html += day === null ? "<p>Nothing to buy: the pantry covers the week.</p>" : "</tbody></table>";
  if (table) html += "<p><b>About $" + total.toFixed(2) + "</b> at " + esc(levelName)
    + (list.left_total >= 0.005 ? ", including $" + list.left_total.toFixed(2) + " of food left over" : "") + "."
    + (buy.some((l) => l.estimated) ? " Prices in italics are estimates." : "")
    + (data.unpriced.length ? " No price for: " + esc(data.unpriced.sort().join(", ")) + "." : "") + "</p>";
  else html += "<p class=\"note\">There are no prices called " + esc(levelName) + ", so no costs are shown.</p>";
  if (data.not_bought.length) html += "<p class=\"note\">Needed but free, so not on the list: " + esc(data.not_bought.sort().join(", ")) + ".</p>";
  if (covered.length) html += "<p class=\"note\">In the pantry already: " + covered.map((l) => esc(l.food) + " (" + number(l.need, 0) + " g needed, " + number(l.have, 0) + " g there)").join(", ") + ".</p>";
  const loose = Object.keys(n.unquantified).sort();
  if (loose.length) html += "<p class=\"note\">Check you have some of these, as the recipe gives no amount: " + loose.map((f) => esc(f) + " (" + esc(n.unquantified[f].join(", ")) + ")").join(", ") + ".</p>";
  data.covered = covered.map((l) => ({food: l.food, need: l.need, have: l.have}));
  data.unquantified = n.unquantified;
  html += "<script>document.querySelectorAll('input[data-item]').forEach(function (box) {"
    + "try { box.checked = localStorage.getItem('shop:' + box.dataset.item) === '1'; } catch (e) {}"
    + "box.addEventListener('change', function () { try { localStorage.setItem('shop:' + box.dataset.item, box.checked ? '1' : '0'); } catch (e) {} "
    + "box.closest('tr').classList.toggle('done', box.checked); });"
    + "box.closest('tr').classList.toggle('done', box.checked); });</script>";
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
