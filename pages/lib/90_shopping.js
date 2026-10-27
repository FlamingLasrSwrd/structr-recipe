// A committed week's shopping list (mealplanner/shopping.py): what its meals not yet cooked still need,
// less eligible stock, with a cost at a price level. The shopping page, and the shoppingList method.

const COUNT = ["each", "whole", "count"];
const PRICE_KIND = "Unit Price", PRICE_HIERARCHY = "Price Reference";

// prices.price_table and food_price: a level's Unit Price defaults by food, nearest level first;
// a food without one takes its nearest priced ancestor's
function priceTable(levelName) {
  const level = $.find("DomainType", {name: levelName})[0];
  if (!level) return null;
  const table = {};
  for (const lv of ancestorsOrSelf(level)) {
    for (const d of defaultsOf(lv, PRICE_KIND)) {
      if ((d.keyedBy || []).length !== 1) continue;
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

// shopping.shopping_list: {zone, priced, cooks, leftovers, buy (lines to buy, by the day first needed,
// then food), covered, unquantified, not_bought, unpriced, total}. A line: {food, need, have, buy,
// first, recipes, optional, each, cost, estimated}. ownOnly: only stock private to the caller counts
// (a household's own; ownStock in 50_pantry.js), as for a household's method
function shoppingFor(week, levelName, ownOnly) {
  const zone = weekZone(week);
  const table = priceTable(levelName);
  const portions = $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))
    .filter((p) => !ownOnly || p.visibleToAuthenticatedUsers === false);
  const n = needs(week);
  const lines = [], notBought = [], unpriced = [];
  for (const id of Object.keys(n.pools)) {
    const p = n.pools[id];
    const have = eligibleGrams(p.food, portions);
    const line = {food: p.food.name, need: p.need, have: have, buy: Math.max(0, p.need - have), first: p.first,
                  recipes: p.recipes, optional: p.optional, each: p.counted ? toGrams(p.food, 1, "each") : null, cost: null, estimated: false};
    if (line.buy > 0 && table) {
      const price = foodPrice(table, p.food);
      const value = price && price.hasValue ? price.hasValue.value : null;
      if (value === 0) { notBought.push(line.food); continue; }
      if (value != null) { line.cost = line.buy * value / 100; line.estimated = price.provenance === "estimated"; }
      else unpriced.push(line.food);
    }
    lines.push(line);
  }
  const buy = lines.filter((l) => l.buy > 0), covered = lines.filter((l) => l.buy <= 0).sort((a, b) => a.food.localeCompare(b.food));
  for (const food of Object.keys(n.unquantified)) if (lines.some((l) => l.food === food) || notBought.indexOf(food) >= 0) delete n.unquantified[food];
  buy.sort((a, b) => (a.first ? dayKey(a.first, zone) : "~").localeCompare(b.first ? dayKey(b.first, zone) : "~") || a.food.localeCompare(b.food));
  return {zone: zone, priced: !!table, cooks: n.cooks, leftovers: n.leftovers, buy: buy, covered: covered,
          unquantified: n.unquantified, not_bought: notBought, unpriced: unpriced, total: buy.reduce((s, l) => s + (l.cost || 0), 0)};
}
