// A food bought in place of what the shopping list says, and the alternatives the shopping page offers
// (mealplanner/substitutes.py, mealplanner/alternatives.py): which rules a planned meal uses, what it then
// takes, what that does to its nutrition, the alternatives to a line's food best first, and the bookings
// "bought instead" and "undo the swap" (SWAP_ACTIONS), shared by the shopping and week pages.

const COUNTED = ["each", "whole", "count"];
const MAX_SIMILAR = 6, MAX_CONSIDERED = 40, ENERGY_NUTRIENT = "Energy";   // alternatives.MAX_SIMILAR, ...

// substitutes.entry_swaps: {input Specification id: {rule, food, ratio, oneOff}}; a rule that rules its food
// out, or names no input or food, is not a swap; of two for one input, the first by name
function entrySwaps(entry) {
  const out = {};
  const rules = (entry.usesSubstitution || []).slice()
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")) || String(a.id).localeCompare(String(b.id)));
  for (const rule of rules) {
    const spec = rule.forSpecification, food = rule.candidateType;
    if (!spec || !food || rule.isExcluded || out[spec.id]) continue;
    out[spec.id] = {rule: rule, food: food, ratio: rule.substitutionRatio == null ? 1 : rule.substitutionRatio, oneOff: !!rule.isOneOff};
  }
  return out;
}

// substitutes.swapped_grams: grams of what stands in, for an input's quantity as the recipe states it
function swappedGrams(original, q, swap) {
  if (!q || q.value == null) return null;
  if (!swap.oneOff) {
    const grams = toGrams(swap.food, q.value * swap.ratio, q.unit);
    if (grams) return grams;
  }
  const was = toGrams(original, q.value, q.unit);
  return was ? was * swap.ratio : null;
}

// substitutes.entry_inputs: [{spec, food, grams (unscaled, null when none converts), counted, original, swap}]
function entryInputs(entry, specs) {
  const swaps = (entry.usesSubstitution || []).length ? entrySwaps(entry) : {};
  const out = [];
  for (const spec of specs) {
    const food = spec.specifies, q = spec.hasSpecifiedQuantity;
    if (!food) continue;
    const counted = !!q && COUNTED.indexOf(String(q.unit || "").trim().toLowerCase()) >= 0;
    const swap = swaps[spec.id];
    if (!swap) out.push({spec: spec, food: food, grams: q && q.value != null ? toGrams(food, q.value, q.unit) || null : null,
                         counted: counted, original: null, swap: null});
    else out.push({spec: spec, food: swap.food, grams: swappedGrams(food, q, swap), counted: counted && !swap.oneOff, original: food, swap: swap});
  }
  return out;
}

// substitutes.source_entry: the planned meal whose cook an entry eats
function sourceEntry(entry) {
  const seen = {};
  let current = entry;
  for (let hop = 0; hop <= 20 && current; hop++) {
    if (current.references) return current;
    const source = current.consumesLeftoverFrom;
    if (!source || seen[source.id]) return null;
    seen[source.id] = true;
    current = source;
  }
  return null;
}

// nutrition_scope.profile_figure: a Type's own profile for a nutrient on a basis, or null; two are an error
function profileFigure(food, nutrientId, basis) {
  const found = (food.nutrientProfilesAbout || []).filter((p) => p.forNutrient && p.forNutrient.id === nutrientId && p.basis === basis);
  if (!found.length) return null;
  if (found.length > 1) throw new Error(food.name + " has " + found.length + " " + basis + " profiles for one nutrient");
  return found[0].amount == null ? null : found[0];
}

// nutrition_scope.retention_factor: a RetentionFactor keyed by the nutrient and, optionally, the method
function retentionFactor(food, methodId, nutrientId) {
  if (!$.find("DomainType", {name: "RetentionFactor"}).length) return null;
  const d = resolveDefault(food, "RetentionFactor", [nutrientId].concat(methodId ? [methodId] : []));
  if (!d) return null;
  const v = d.hasValue;
  if (!(d.keyedBy || []).some((k) => k.id === nutrientId) || !v || v.unit !== "ratio" || v.value == null || v.value < 0) {
    throw new Error("RetentionFactor " + d.name + " must be keyed by its nutrient and be a non-negative ratio");
  }
  return v.value;
}

// substitutes._contribution: [what an input brings to the dish in `unit` or null, its profile's provenance, whether unadjusted]
function contribution(food, grams, count, methodId, nutrientId, unit) {
  let figure = profileFigure(food, nutrientId, "per_100g"), perUnit = false;
  if (!figure) { figure = profileFigure(food, nutrientId, "per_unit"); perUnit = true; }
  if (!figure) return [null, null, false];
  const perBasis = convertNutrient(figure.amount, figure.unit, unit);
  if (perBasis == null) return [null, figure.provenance, false];
  if (perBasis === 0) return [0, figure.provenance, false];
  let amount;
  if (perUnit) { if (count == null) return [null, figure.provenance, false]; amount = count * perBasis; }
  else { if (grams == null) return [null, figure.provenance, false]; amount = grams * perBasis / 100; }
  const factor = retentionFactor(food, methodId, nutrientId);
  return [amount * (factor == null ? 1 : factor), figure.provenance, factor == null];
}

// substitutes.swap_delta: [what a meal's swaps change in ONE serving, or null; whether it rests on an estimate]
function swapDelta(entry, plan, nutrientId, unit, servings) {
  const swaps = entrySwaps(entry);
  if (!Object.keys(swaps).length) return [0, false];
  let total = 0, estimated = false;
  for (const [step, spec] of rawInputs(plan)) {
    const swap = swaps[spec.id];
    if (!swap) continue;
    const method = step.instanceOf ? step.instanceOf.id : null, q = spec.hasSpecifiedQuantity || {};
    const counted = COUNTED.indexOf(String(q.unit || "").trim().toLowerCase()) >= 0;
    const original = spec.specifies;
    const before = contribution(original, q.value != null ? toGrams(original, q.value, q.unit) : null, counted ? q.value : null, method, nutrientId, unit);
    const after = contribution(swap.food, swappedGrams(original, q, swap),
                               counted && q.value != null && !swap.oneOff ? q.value * swap.ratio : null, method, nutrientId, unit);
    if (before[0] == null || after[0] == null) return [null, false];
    if (USABLE.indexOf(after[1]) < 0 || USABLE.indexOf(before[1]) < 0) return [null, false];
    total += after[0] - before[0];
    estimated = estimated || after[1] !== "sourced" || after[2] || swap.oneOff;
  }
  return [total / servings, estimated];
}

// recipe_nutrition.targeted_nutrients: {nutrient id: [name, unit]}, the unit of the first target on it by name
function targetedNutrients() {
  const out = {};
  const targets = $.find("NutritionTarget").slice()
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")) || String(a.id).localeCompare(String(b.id)));
  for (const t of targets) {
    const n = t.forNutrient, r = t.hasTargetRange;
    if (!n || !r || out[n.id] || !NUTRIENT_UNITS[String(r.unit || "").trim().toLowerCase()]) continue;
    out[n.id] = [n.name, r.unit];
  }
  return out;
}

// substitutes.meals_needing: [{entry, specs}]: the week's cooks still to make whose recipe takes the food or a
// food below it as an input it does not make, for an input no swap already stands in for
function mealsNeeding(week, food) {
  const pool = subtypesOf(food), out = [];
  for (const entry of week.hasEntry || []) {
    if (entry.isSkipped || entry.fulfilledBy || !entry.references || entry.hasPlannedServings == null) continue;
    const specs = [].concat(...(entry.references.steps || []).map((s) => s.hasSpecification || []));
    const produced = {};
    for (const s of specs) if (s.hasParticipationRole === "output" && s.specifies) produced[s.specifies.id] = true;
    const swapped = (entry.usesSubstitution || []).length ? entrySwaps(entry) : {};
    const mine = specs.filter((s) => s.hasParticipationRole === "input" && s.specifies && pool[s.specifies.id]
                                      && !produced[s.specifies.id] && !swapped[s.id]);
    if (mine.length) out.push({entry: entry, specs: mine});
  }
  return out;
}

// alternatives._uses: [{entry, spec, step, scale, grams}] for the meals needing the food
function usesOf(week, food) {
  const out = [];
  for (const {entry, specs} of mealsNeeding(week, food)) {
    const plan = entry.references, y = plan.hasRecipeYield;
    if (!y || y.unit !== "servings" || !(y.value > 0)) continue;
    const scale = entry.hasPlannedServings / y.value, steps = {};
    for (const [step, spec] of rawInputs(plan)) steps[spec.id] = step;
    for (const spec of specs) {
      const q = spec.hasSpecifiedQuantity, grams = q && q.value != null ? toGrams(spec.specifies, q.value, q.unit) : null;
      out.push({entry: entry, spec: spec, step: steps[spec.id] || null, scale: scale, grams: grams ? grams * scale : null});
    }
  }
  return out;
}

const byName = (nutrients) => Object.keys(nutrients).sort((a, b) => nutrients[a][0].localeCompare(nutrients[b][0]));

// alternatives.effect: [{cost, nutrients: [[name, unit, change]]}, grams of what stands in]
function swapEffect(uses, swapOf, prices, nutrients) {
  let cost = 0, taken = 0;
  const changes = {};
  for (const id of Object.keys(nutrients)) changes[id] = 0;
  for (const use of uses) {
    const swap = swapOf(use), q = use.spec.hasSpecifiedQuantity || {}, original = use.spec.specifies;
    let grams = swappedGrams(original, q, swap);
    grams = grams ? grams * use.scale : null;
    taken += grams || 0;
    if (cost != null) {
      const before = prices ? foodPrice(prices, original) : null, after = prices ? foodPrice(prices, swap.food) : null;
      const pb = before && before.hasValue ? before.hasValue.value : null, pa = after && after.hasValue ? after.hasValue.value : null;
      cost = pb == null || pa == null || grams == null || use.grams == null ? null : cost + (grams * pa - use.grams * pb) / 100;
    }
    if (!use.step) continue;
    const method = use.step.instanceOf ? use.step.instanceOf.id : null;
    const counted = q.value != null && COUNTED.indexOf(String(q.unit || "").trim().toLowerCase()) >= 0;
    for (const id of Object.keys(nutrients)) {
      if (changes[id] == null) continue;
      const unit = nutrients[id][1];
      const was = contribution(original, use.grams ? use.grams / use.scale : null, counted ? q.value : null, method, id, unit)[0];
      const now = contribution(swap.food, grams ? grams / use.scale : null, counted && !swap.oneOff ? q.value * swap.ratio : null, method, id, unit)[0];
      changes[id] = was == null || now == null ? null : changes[id] + (now - was) * use.scale;
    }
  }
  return [{cost: cost, nutrients: byName(nutrients).map((id) => [nutrients[id][0], nutrients[id][1], changes[id]])}, taken];
}

const haveOf = (food) => eligibleLots(food, {household: null}).reduce((s, lot) => s + lot.grams, 0);

// alternatives._energy: kcal per 100 g, or null
function energyOf(food) {
  const found = $.find("DomainType", {name: ENERGY_NUTRIENT});
  if (found.length !== 1) return null;
  const figure = profileFigure(food, found[0].id, "per_100g");
  return figure ? convertNutrient(figure.amount, figure.unit, "kcal") : null;
}

// alternatives.neighbours: foods beside one, nearest first, none of leaveOut or the products, by name per distance
function neighbours(food, leaveOut, products) {
  const found = [], seen = Object.assign({}, leaveOut, subtypesOf(food));
  let above = food.parent;
  for (const depth of [2, 3]) {
    if (!above || found.length >= MAX_SIMILAR) break;
    const level = [];
    let frontier = [above];
    for (let i = 0; i < depth; i++) {
      const next = [];
      for (const t of frontier) {
        for (const child of t.children || []) {
          if (seen[child.id]) continue;
          seen[child.id] = true;
          next.push(child);
          if (!products[child.id]) level.push(child);
        }
      }
      frontier = next;
    }
    level.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    found.push(...level);
    above = above.parent;
  }
  return found.slice(0, MAX_CONSIDERED);
}

// alternatives.alternatives: {food, grams, meals: [[entry, recipe]], options: [{kind, food, meals, grams, have, ratio,
// effect, kinds, checked}]}
function alternativesFor(week, food, prices, nutrients) {
  const uses = usesOf(week, food), meals = [], seen = {};
  for (const use of uses) if (!seen[use.entry.id]) { seen[use.entry.id] = true; meals.push([use.entry.name, use.entry.references.name]); }
  const entryNames = meals.map((m) => m[0]);
  const products = productIds();
  const total = uses.reduce((s, u) => s + (u.grams || 0), 0);
  const option = (kind, name, names, grams, have, ratio, effect, kinds) =>
    ({kind: kind, food: name, meals: names, grams: grams, have: have, ratio: ratio, effect: effect, kinds: kinds || [], checked: kind !== "similar"});
  const kinds = [], todo = (food.children || []).slice(), met = {};
  while (todo.length) {
    const t = todo.pop();
    if (met[t.id]) continue;
    met[t.id] = true;
    kinds.push(t.name);
    todo.push(...(t.children || []));
  }
  kinds.sort();
  const options = [option("same", null, entryNames, total, haveOf(food), null,
                          {cost: 0, nutrients: byName(nutrients).map((id) => [nutrients[id][0], nutrients[id][1], 0])}, kinds)];
  // the recipes' own rules, grouped by what stands in
  const ruledOut = {}, byFood = {}, order = [];
  for (const use of uses) {
    for (const rule of use.spec.hasSubstitutionRule || []) {
      const cand = rule.candidateType;
      if (!cand || rule.isOneOff) continue;
      if (rule.isExcluded) { ruledOut[cand.id] = true; continue; }
      if (!byFood[cand.id]) { byFood[cand.id] = []; order.push(cand.id); }
      byFood[cand.id].push([use, {rule: rule, food: cand, ratio: rule.substitutionRatio == null ? 1 : rule.substitutionRatio, oneOff: false}]);
    }
  }
  const recipeOptions = order.map((id) => {
    const pairs = byFood[id], covered = pairs.map((p) => p[0]);
    const [effect, grams] = swapEffect(covered, (u) => pairs.find((p) => p[0] === u)[1], prices, nutrients);
    const names = [];
    for (const u of covered) if (names.indexOf(u.entry.name) < 0) names.push(u.entry.name);
    const ratios = pairs.map((p) => p[1].ratio).filter((r, i, a) => a.indexOf(r) === i);
    return option("recipe", pairs[0][1].food.name, names, grams, haveOf(pairs[0][1].food), ratios.length === 1 ? ratios[0] : null, effect);
  });
  const key = (a) => [a.have <= 0 ? 1 : 0, a.meals.length < entryNames.length ? 1 : 0, a.effect.cost == null ? 1 : 0, a.effect.cost || 0];
  recipeOptions.sort((a, b) => {
    const ka = key(a), kb = key(b);
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i];
    return a.food < b.food ? -1 : a.food > b.food ? 1 : 0;
  });
  options.push(...recipeOptions);
  // foods beside it, one to one by weight, not checked against a recipe
  const target = energyOf(food), leave = Object.assign({}, ruledOut);
  for (const id of order) leave[id] = true;
  const ranked = neighbours(food, leave, products).map((cand) => {
    const energy = energyOf(cand), priced = !!(prices && foodPrice(prices, cand));
    return [(energy == null ? 1 : 0) + (priced ? 0 : 1), energy != null && target != null ? Math.abs(energy - target) : Infinity, cand.name, cand];
  });
  ranked.sort((a, b) => a[0] - b[0] || (a[1] === b[1] ? 0 : a[1] < b[1] ? -1 : 1) || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0));
  for (const r of ranked.slice(0, MAX_SIMILAR)) {
    const swap = {rule: null, food: r[3], ratio: 1, oneOff: true};
    const [effect, grams] = swapEffect(uses, () => swap, prices, nutrients);
    options.push(option("similar", r[2], entryNames, grams, haveOf(r[3]), 1, effect));
  }
  options.push(option("replan", null, entryNames, 0, 0, null, null));
  return {food: food.name, grams: total, meals: meals, options: options};
}

// substitutes.recipe_rule: the recipe's own rule on an input whose candidate is the bought food or above it
function recipeRule(spec, bought) {
  const above = ancestorsOrSelf(bought).map((t) => t.id);
  let best = null;
  for (const rule of spec.hasSubstitutionRule || []) {
    const food = rule.candidateType;
    if (rule.isOneOff || !food || above.indexOf(food.id) < 0) continue;
    const rank = above.indexOf(food.id);
    if (!best || rank < best[0]) best = [rank, rule];
  }
  return best ? best[1] : null;
}

// substitutes.use_instead: the week's meals needing `listed` use `bought`, by the recipe's own rule or a one-off
// rule one to one by weight; only the meals in `entryIds` when given. Notes go on the booking
function useInstead(booking, week, listed, bought, entryIds) {
  if (subtypesOf(listed)[bought.id]) throw new BookingError(bought.name + " is " + listed.name + " already: a product or kind of it stands in for it with no swap");
  if (productIds()[bought.id] && bought.parent) bought = bought.parent;     // a product has no figures: the meals use its food
  let changed = 0;
  for (const {entry, specs} of mealsNeeding(week, listed)) {
    if (entryIds && entryIds.indexOf(entry.id) < 0) continue;
    if (booking.household && entry.visibleToAuthenticatedUsers !== false) continue;
    const uses = (entry.usesSubstitution || []).slice(), added = [];
    for (const spec of specs) {
      let rule = recipeRule(spec, bought), how;
      if (rule && rule.isExcluded) {
        booking.notes.push(entry.name + ": the recipe says " + bought.name + " must not stand in for " + spec.specifies.name + ", so it is left as it is.");
        continue;
      }
      if (!rule) {
        rule = ensureNode(booking, "SubstitutionRule", (spec.name || spec.id) + " or " + bought.name + " (bought instead)",
                          {forSpecification: spec, candidateType: bought, substitutionRatio: 1.0, isOneOff: true, isExcluded: false});
        how = "one to one by weight";
      } else {
        const r = rule.substitutionRatio;
        how = "by the recipe's own rule" + (r == null || r === 1 ? "" : ", " + r + " for 1");
      }
      if (!uses.some((u) => u.id === rule.id) && !added.some((u) => u.id === rule.id)) {
        added.push(rule);
        booking.notes.push(entry.name + ": " + bought.name + " for " + spec.specifies.name + ", " + how + ".");
      }
    }
    if (added.length) { entry.usesSubstitution = uses.concat(added); changed++; }
  }
  if (!changed && !booking.notes.length) booking.notes.push("No meal of the week still to cook needs " + listed.name + ".");
  return changed;
}

// The week a booking names; a household's own only
function swapWeek(r, booking) {
  const found = $.find("MealPlan", {id: String(r.week || "")});
  const week = Array.isArray(found) ? found[0] : found;
  if (!week || week.type !== "MealPlan") throw new BookingError("no such week");
  if (booking.household && week.visibleToAuthenticatedUsers !== false) throw new BookingError(week.name + ": not your household's week");
  return week;
}

const SWAP_ACTIONS = {
  // substitutes.buy_instead: the purchase (pantry.buy), and the week's meals that needed the listed food use it
  instead: (booking, r, token) => {
    let ready = false;
    const look = () => { ready = $.find("SchemaRelationshipNode", {relationshipType: "USES_SUBSTITUTION"}).length > 0; };
    if (typeof $.doPrivileged === "function") $.doPrivileged(look); else look();
    if (!ready) {
      throw new BookingError("this instance cannot record a swap yet: run scripts/51a_swap_schema.py, then restart Structr");
    }
    const week = swapWeek(r, booking);
    const listed = typeNamed(String(r.listed || "").trim()), bought = typeNamed(String(r.food || "").trim());
    const entries = String(r.entries || "").split(",").map((s) => s.trim()).filter((s) => s);
    useInstead(booking, week, listed, bought, entries.length ? entries : null);
    PANTRY_ACTIONS.buy(booking, {food: bought.name, amount: r.amount, unit: r.unit, storage: r.storage}, token);
  },
  // substitutes.stop_using: a meal no longer uses a rule; a one-off rule no meal uses any more is deleted
  unswap: (booking, r) => {
    const entry = entryNamed(r, booking);
    if (entry.fulfilledBy) throw new BookingError(entry.name + ": cooked already, with the swap");
    const uses = entry.usesSubstitution || [], rule = uses.find((u) => u.id === String(r.rule || ""));
    if (!rule) throw new BookingError(entry.name + ": uses no such swap");
    entry.usesSubstitution = uses.filter((u) => u.id !== rule.id);
    booking.process = entry.name;
    booking.created.push(entry.name + " without " + rule.name);
    booking.notes.push(entry.name + ": uses " + (rule.forSpecification && rule.forSpecification.specifies ? rule.forSpecification.specifies.name : "the recipe's food") + " again.");
    if (rule.isOneOff && !(rule.usedByEntries || []).some((e) => e.id !== entry.id) && !(rule.allocationsVia || []).length) {
      $.delete(rule);
    }
  },
};
