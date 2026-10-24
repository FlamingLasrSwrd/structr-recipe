// /structr/html/shopping[/<MealPlan id>][?prices=<price level>]: a committed week's shopping list, as
// mealplanner/shopping.py makes it: what the week's committed, not yet cooked meals call for (scaled by
// servings planned over the recipe's yield), less eligible stock on hand, by the day each food is first
// needed, with a cost at a price level. Stock policies' target levels are not applied here (the owner
// has none, 2026-10-23); with one in the graph the page says so, and tools/shopping_list.py applies it.

const GRAMS_PER_LB = 453.592, GRAMS_PER_OZ = 28.3495;
const COUNT = ["each", "whole", "count"];
const PRICE_KIND = "Unit Price", PRICE_HIERARCHY = "Price Reference";

// shopping.Line.amount
function amountText(grams, each) {
  if (each) return Math.ceil(grams / each - 1e-9) + " (about " + number(grams, 0) + " g)";
  if (grams >= GRAMS_PER_LB / 2) return number(grams, 0) + " g (" + (grams / GRAMS_PER_LB).toFixed(1) + " lb)";
  if (grams >= GRAMS_PER_OZ) return number(grams, 0) + " g (" + (grams / GRAMS_PER_OZ).toFixed(1) + " oz)";
  return number(grams, 0) + " g";
}

// prices.price_table and food_price: a level's Unit Price defaults by food, nearest level first;
// a food without one takes its nearest priced ancestor's
function priceTable(levelName) {
  const level = $.find("DomainType", {name: levelName})[0];
  if (!level) return null;
  const table = {};
  for (const lv of ancestorsOrSelf(level)) {
    for (const d of lv.defaultSpecifications || []) {
      if (!d.hasKind || d.hasKind.name !== PRICE_KIND || (d.keyedBy || []).length !== 1) continue;
      const food = d.keyedBy[0].id;
      if (!(food in table)) table[food] = d;
    }
  }
  return table;
}
function foodPrice(table, food) {
  for (const t of ancestorsOrSelf(food)) if (t.id in table) return table[t.id];
  return null;
}

// reservation.committed_requirements and shopping.shopping_list's walk of the entries
function needs(week) {
  const pools = {}, unquantified = {};
  let cooks = 0, leftovers = 0;
  for (const entry of activeEntries(week)) {
    if (entry.fulfilledBy) continue;
    if (!entry.references || entry.hasPlannedServings == null) { leftovers++; continue; }
    cooks++;
    const plan = entry.references, start = startOf(entry);
    const y = plan.hasRecipeYield;
    const scale = y && y.unit === "servings" && y.value > 0 ? entry.hasPlannedServings / y.value : null;
    const specs = [].concat(...(plan.steps || []).map((s) => s.hasSpecification || []));
    const produced = new Set(specs.filter((s) => s.hasParticipationRole === "output" && s.specifies).map((s) => s.specifies.id));
    for (const spec of specs) {
      const food = spec.specifies;
      if (spec.hasParticipationRole !== "input" || !food || produced.has(food.id)) continue;
      const q = spec.hasSpecifiedQuantity;
      const grams = q && q.value != null ? toGrams(food, q.value, q.unit) : null;
      if (!grams || scale == null) {
        const used = unquantified[food.name] = unquantified[food.name] || [];
        if (used.indexOf(plan.name) < 0) used.push(plan.name);
        continue;
      }
      const p = pools[food.id] = pools[food.id] || {food: food, need: 0, recipes: [], first: null, optional: true, counted: false};
      p.need += grams * scale;
      if (p.recipes.indexOf(plan.name) < 0) p.recipes.push(plan.name);
      if (start && (!p.first || start < p.first)) p.first = start;
      p.optional = p.optional && !!spec.isOptional;
      p.counted = p.counted || COUNT.indexOf(String(q.unit || "").trim().toLowerCase()) >= 0;
    }
  }
  return {pools: pools, unquantified: unquantified, cooks: cooks, leftovers: leftovers};
}

// inventory.eligible_on_hand_with_urgency, with no policy filters: positive, unexpired stock of the type
// or any type below it
function eligibleGrams(food, portions) {
  const types = subtypesOf(food);
  let total = 0;
  for (const portion of portions) {
    if (!portion.instanceOf || !types[portion.instanceOf.id]) continue;
    const level = onHand(portion);
    if (!Array.isArray(level) || !(level[0] > 0)) continue;
    const [days] = daysUntilExpiry(portion);
    if (days != null && days < 0) continue;
    total += level[0];
  }
  return total;
}

const week = chosenWeek();
const levelName = $.request.prices || "Home prices";
let html = nav("shopping") + "<h1>Shopping list</h1>";
const data = {to_buy: [], covered: [], unquantified: {}, not_bought: [], unpriced: []};
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const zone = weekZone(week);
  const table = priceTable(levelName);
  const portions = $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"));
  const n = needs(week);
  const lines = [];
  for (const id of Object.keys(n.pools)) {
    const p = n.pools[id];
    const have = eligibleGrams(p.food, portions);
    const line = {food: p.food.name, need: p.need, have: have, buy: Math.max(0, p.need - have), first: p.first,
                  recipes: p.recipes, optional: p.optional, each: p.counted ? toGrams(p.food, 1, "each") : null, cost: null, estimated: false};
    if (line.buy > 0 && table) {
      const price = foodPrice(table, p.food);
      const value = price && price.hasValue ? price.hasValue.value : null;
      if (value === 0) { data.not_bought.push(line.food); continue; }
      if (value != null) { line.cost = line.buy * value / 100; line.estimated = price.provenance === "estimated"; }
      else data.unpriced.push(line.food);
    }
    lines.push(line);
  }
  const buy = lines.filter((l) => l.buy > 0), covered = lines.filter((l) => l.buy <= 0).sort((a, b) => a.food.localeCompare(b.food));
  for (const food of Object.keys(n.unquantified)) if (lines.some((l) => l.food === food) || data.not_bought.indexOf(food) >= 0) delete n.unquantified[food];
  buy.sort((a, b) => (a.first ? dayKey(a.first, zone) : "~").localeCompare(b.first ? dayKey(b.first, zone) : "~") || a.food.localeCompare(b.food));
  const total = buy.reduce((s, l) => s + (l.cost || 0), 0);
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
