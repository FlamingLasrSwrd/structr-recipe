// A committed week's shopping list (mealplanner/shopping.py): what its meals not yet cooked still need,
// less eligible stock, rounded up to what each food is sold in at a package level, with what will be
// left and until when, and a cost at a price level. The shopping page, and the shoppingList method.

const COUNT = ["each", "whole", "count"];
const PRICE_KIND = "Unit Price", PRICE_HIERARCHY = "Price Reference";
const PACKAGE_KIND = "PurchaseQuantity", PUBLIC_PACKAGES = "US supermarket", HOME_PACKAGES = "Home packages";
const SLACK = 1e-6, LEFT_G = 0.5, SHORT_G = 1e-3;   // packages.SLACK, shopping.LEFT_G, shopping.SHORT_G

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

// packages.default_level: the owner's package level where there is one, else the public one, else null
function defaultPackageLevel() {
  for (const name of [HOME_PACKAGES, PUBLIC_PACKAGES]) if ($.find("DomainType", {name: name})[0]) return name;
  return null;
}

// packages.package_table: food id -> its sizes, [{amount, unit, label, estimated}], seen from a level; the
// nearest level that gives a food any size gives all of them, ordered by the default's name
function packageTable(levelName) {
  const level = levelName ? $.find("DomainType", {name: levelName})[0] : null;
  if (!level) return null;
  const table = {};
  for (const lv of ancestorsOrSelf(level)) {
    const here = {};
    for (const d of defaultsOf(lv, PACKAGE_KIND)) {
      if ((d.keyedBy || []).length !== 1 || !d.hasValue) continue;
      const food = d.keyedBy[0], prefix = lv.name + " -- " + food.name + " -- ";
      const label = d.name.indexOf(prefix) === 0 ? d.name.slice(prefix.length) : d.hasValue.value + " " + String(d.hasValue.unit).replace("_", " ");
      (here[food.id] = here[food.id] || []).push({name: d.name, amount: d.hasValue.value, unit: d.hasValue.unit, label: label,
                                                   estimated: d.provenance === "estimated"});
    }
    for (const id of Object.keys(here)) {
      if (!(id in table)) table[id] = here[id].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    }
  }
  return table;
}
function foodPackages(table, food) {
  for (const t of ancestorsOrSelf(food)) if (t.id in table) return table[t.id];
  return [];
}

// packages.choose: how many of each size (grams, in order) for `need` grams: least left over, then the
// fewest packages, then the smallest counts of the sizes listed first
function choosePackages(sizes, need) {
  if (need <= 0 || !sizes.length) return sizes.map(() => 0);
  const target = need * (1 - SLACK);
  let best = null, bestKey = null;
  const less = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i]; return false; };
  function visit(i, counts, total) {
    if (i === sizes.length - 1) {
      const last = Math.max(0, Math.ceil((target - total) / sizes[i]));
      const full = counts.concat([last]);
      const bought = total + last * sizes[i];
      const key = [Math.floor((bought - need) * 1e6 + 0.5), full.reduce((s, n) => s + n, 0)].concat(full);
      if (bestKey === null || less(key, bestKey)) { best = full; bestKey = key; }
      return;
    }
    const top = Math.max(0, Math.ceil((target - total) / sizes[i]));
    for (let n = 0; n <= top; n++) visit(i + 1, counts.concat([n]), total + n * sizes[i]);
  }
  visit(0, [], 0);
  return best;
}

// shopping.left_over_keeps: [until when what is left keeps, whether as opened]: the longest opened figure of
// the fridge's and the pantry's, else unopened where the pantry assumes it kept; both from its first use
function leftOverKeeps(food, firstUse) {
  const opened = typeId("Opened");
  if (!typeId("ShelfLife") || !opened) return [null, false];
  let best = null;
  for (const storage of ["Fridge", "Pantry"]) {
    const where = typeId(storage);
    const d = where ? resolveDefault(food, "ShelfLife", [where, opened]) : null;
    if (d && (d.keyedBy || []).some((k) => k.id === opened) && d.hasValue && d.hasValue.value != null && (best === null || d.hasValue.value > best)) best = d.hasValue.value;
  }
  if (best !== null) return [new Date(firstUse.getTime() + best * 86400e3), true];
  const portion = {instanceOf: food};
  const days = portionShelfLife(portion, [typeId(assumedStorage(portion)), typeId("Sealed")]);
  return days != null ? [new Date(firstUse.getTime() + days * 86400e3), false] : [null, false];
}

// yields.edible_fraction: [of a gram as bought, what a recipe weighs; what is cut away]: the food's own
// trim or its nearest ancestor's, a Yield keyed by Trimming alone whose target is the Type it is on
function edibleFraction(food) {
  for (const t of ancestorsOrSelf(food)) {
    for (const d of defaultsOf(t, "Yield")) {
      const keys = d.keyedBy || [];
      if (keys.length !== 1 || keys[0].name !== "Trimming" || !d.targetType || d.targetType.id !== t.id) continue;
      const v = d.hasValue;
      if (v && v.unit === "ratio" && v.value > 0 && v.value <= 1) {
        const source = d.source || "", at = source.indexOf("cut away: ");
        return [v.value, at < 0 ? "" : source.slice(at + 10).split(";")[0].trim()];
      }
    }
  }
  return [1, ""];
}

// yields.made_from: {source, factor} for the food this one is bought as, a Yield on another food whose
// target is this one, the first by name; null if none
function madeFrom(food) {
  const found = (food.yieldTargetOf || []).filter((d) => d.hasKind && d.hasKind.name === "Yield" && d.forType
    && d.forType.id !== food.id && (d.keyedBy || []).length === 1 && d.hasValue && d.hasValue.unit === "ratio" && d.hasValue.value > 0);
  if (!found.length) return null;
  found.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return {source: found[0].forType, factor: found[0].hasValue.value};
}

// shopping._round_up: whole packages of the sizes the food is sold in, or whole items of a food the
// recipes count, or as much as is needed; a food with a trim bought by weight as it is sold (a package
// by weight or volume holds `edible` of it as a recipe weighs it, a loose need is bought over it)
function roundUp(line, food, packages) {
  const found = [];
  for (const p of packages ? foodPackages(packages, food) : []) {
    const grams = toGrams(food, p.amount, p.unit);
    if (grams) found.push([grams, p, COUNT.indexOf(String(p.unit).trim().toLowerCase()) >= 0]);
  }
  if (found.some((f) => !f[2]) || !(found.length || line.each)) [line.edible, line.trimmed] = edibleFraction(food);
  const sizes = found.map((f) => [f[2] ? f[0] : f[0] * line.edible, f[0], f[1]]);
  if (sizes.length) {
    const counts = choosePackages(sizes.map((s) => s[0]), line.buy);
    line.packages = [];
    let bought = 0, asBought = 0;
    counts.forEach((n, i) => {
      bought += n * sizes[i][0];
      asBought += n * sizes[i][1];
      if (n) { line.packages.push({count: n, label: sizes[i][2].label}); line.estimated_size = line.estimated_size || sizes[i][2].estimated; }
    });
    line.bought = bought;
    line.as_bought = asBought;
    line.pieces = [].concat(...counts.map((n, i) => Array(n).fill(sizes[i][0])));
  } else if (line.each) {
    line.bought = Math.ceil(line.buy / line.each - 1e-9) * line.each;
    line.as_bought = line.bought;
    line.pieces = [line.bought];
  } else {
    line.bought = line.buy;
    line.as_bought = line.buy / line.edible;
    line.pieces = [line.bought];
  }
  line.left = Math.max(0, line.bought - line.buy);
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
    const inputs = specs.filter((s) => s.hasParticipationRole === "input" && s.specifies && !produced.has(s.specifies.id));
    for (const item of entryInputs(entry, inputs)) {          // a food bought instead followed (92_substitutes.js)
      const food = item.food, spec = item.spec, grams = item.grams;
      if (!grams || scale == null) {
        const used = unquantified[food.name] = unquantified[food.name] || [];
        if (used.indexOf(plan.name) < 0) used.push(plan.name);
        continue;
      }
      const p = pools[food.id] = pools[food.id] || {food: food, need: 0, recipes: [], first: null, optional: true, counted: false, instead: []};
      p.need += grams * scale;
      if (item.original && p.instead.indexOf(item.original.name) < 0) p.instead.push(item.original.name);
      if (p.recipes.indexOf(plan.name) < 0) p.recipes.push(plan.name);
      if (start && (!p.first || start < p.first)) p.first = start;
      p.optional = p.optional && !!spec.isOptional;
      p.counted = p.counted || item.counted;
    }
  }
  return {pools: pools, unquantified: unquantified, cooks: cooks, leftovers: leftovers};
}

// inventory.eligible_on_hand_with_urgency, with no policy filters: positive, unexpired stock of the type
// or any type below it, leaving out what is another pool's (reservation._nested_pools: where the list
// needs Butter and Butter (salted), salted stock is the second's alone, not counted for both)
function eligibleGrams(food, portions, pools) {
  const types = subtypesOf(food);
  for (const other of Object.keys(pools).filter((id) => id !== food.id && types[id])) {
    for (const id of Object.keys(subtypesOf(pools[other].food))) delete types[id];
  }
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

// shopping.shopping_list: {zone, priced, packaged, cooks, leftovers, buy (lines to buy, by the day first
// needed, then food), covered, unquantified, not_bought, unpriced, total, left_total}. A line: {food, need,
// have, buy, first, recipes, optional, each, cost, estimated, packages ([{count, label}]), estimated_size,
// bought, left, left_cost, keeps_until, keeps_opened, made ([[food, grams]]: what it is bought to make),
// edible (of a gram as bought, what a recipe weighs), trimmed, as_bought (grams as the shop weighs them), pieces (the
// grams of each package bought, as a recipe weighs them; one for a line bought loose or by count: what ticking it books),
// instead (the foods the recipes name that it is bought in place of: substitutes.py)}.
// ownOnly: only stock private to the caller counts (a household's own; ownStock in 50_pantry.js), as for a
// household's method. packageLevel: a package
// level's name, or null for none
function shoppingFor(week, levelName, ownOnly, packageLevel) {
  const zone = weekZone(week);
  const table = priceTable(levelName);
  const packages = packageTable(packageLevel);
  const portions = $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))
    .filter((p) => !ownOnly || p.visibleToAuthenticatedUsers === false);
  const n = needs(week);
  // shopping.shopping_list's purchased forms: a food another yields and no package level sells in a size of
  // its own is bought as that food, what its own stock leaves of it over the yield joining that food's line
  const boughtAs = {};
  for (const id of Object.keys(n.pools)) {
    if (packages && foodPackages(packages, n.pools[id].food).length) continue;
    const made = madeFrom(n.pools[id].food);
    if (made) boughtAs[id] = made;
  }
  const sources = Object.keys(boughtAs).map((id) => boughtAs[id].source.id);
  for (const id of Object.keys(boughtAs)) if (sources.indexOf(id) >= 0) delete boughtAs[id];   // one step: a source is bought as itself
  for (const id of Object.keys(boughtAs)) {
    const src = boughtAs[id].source;
    if (!n.pools[src.id]) n.pools[src.id] = {food: src, need: 0, recipes: [], first: null, optional: true, counted: false};
  }
  const have = {}, extra = {}, madeFor = {};
  for (const id of Object.keys(n.pools)) have[id] = eligibleGrams(n.pools[id].food, portions, n.pools);
  for (const id of Object.keys(boughtAs)) {
    const p = n.pools[id], short = p.need - have[id];
    if (short < SHORT_G) continue;
    const src = boughtAs[id].source.id, s = n.pools[src];
    extra[src] = (extra[src] || 0) + short / boughtAs[id].factor;
    (madeFor[src] = madeFor[src] || []).push([p.food.name, short]);
    for (const r of p.recipes) if (s.recipes.indexOf(r) < 0) s.recipes.push(r);
    if (p.first && (!s.first || p.first < s.first)) s.first = p.first;
    s.optional = s.optional && p.optional;
    s.counted = s.counted || !!toGrams(s.food, 1, "each");
  }
  const lines = [], notBought = [], unpriced = [];
  for (const id of Object.keys(n.pools)) {
    const p = n.pools[id], need = p.need + (extra[id] || 0), short = need - have[id];
    if (boughtAs[id] && p.need - have[id] >= SHORT_G) continue;     // on the line of the food it is bought as
    if (need <= 0) continue;                                         // a food others are bought as, needing nothing
    const line = {food: p.food.name, need: need, have: have[id], buy: short >= SHORT_G ? short : 0, first: p.first,
                  recipes: p.recipes, optional: p.optional, each: p.counted ? toGrams(p.food, 1, "each") : null, cost: null, estimated: false,
                  packages: [], estimated_size: false, bought: null, left: 0, left_cost: null, keeps_until: null, keeps_opened: false,
                  made: madeFor[id] || [], edible: 1, trimmed: "", as_bought: null, pieces: [], instead: (p.instead || []).slice().sort()};
    if (line.buy > 0) {
      const price = table ? foodPrice(table, p.food) : null;
      const value = price && price.hasValue ? price.hasValue.value : null;
      if (value === 0) { notBought.push(line.food); continue; }
      roundUp(line, p.food, packages);
      if (line.left >= LEFT_G) [line.keeps_until, line.keeps_opened] = leftOverKeeps(p.food, p.first || NOW);
      if (value != null) {
        line.cost = line.bought * value / 100;
        line.left_cost = line.left * value / 100;
        line.estimated = price.provenance === "estimated";
      } else if (table) unpriced.push(line.food);
    }
    lines.push(line);
  }
  const buy = lines.filter((l) => l.buy > 0), covered = lines.filter((l) => l.buy <= 0).sort((a, b) => a.food.localeCompare(b.food));
  const madeNames = [].concat(...buy.map((l) => l.made.map((m) => m[0])));
  for (const food of Object.keys(n.unquantified)) if (lines.some((l) => l.food === food) || notBought.indexOf(food) >= 0 || madeNames.indexOf(food) >= 0) delete n.unquantified[food];
  buy.sort((a, b) => (a.first ? dayKey(a.first, zone) : "~").localeCompare(b.first ? dayKey(b.first, zone) : "~") || a.food.localeCompare(b.food));
  return {zone: zone, priced: !!table, packaged: !!packages, cooks: n.cooks, leftovers: n.leftovers, buy: buy, covered: covered,
          unquantified: n.unquantified, not_bought: notBought, unpriced: unpriced, total: buy.reduce((s, l) => s + (l.cost || 0), 0),
          left_total: buy.reduce((s, l) => s + (l.left_cost || 0), 0)};
}
