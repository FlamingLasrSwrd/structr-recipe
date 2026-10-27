// A week's entries: when they are, what they cook, who eats how much, and a recipe's stored nutrition
// per serving (nutrition_scope.py).

// nutrition_scope.entry_start
function startOf(entry) {
  const region = entry.isAbout;
  return region && region.hasBeginning ? new Date(region.hasBeginning) : null;
}

// nutrition_scope.active_entries, in time order (an entry with no start last)
function activeEntries(mealPlan) {
  return (mealPlan.hasEntry || []).filter((e) => !e.isSkipped)
    .sort((a, b) => (startOf(a) || new Date(8.64e15)) - (startOf(b) || new Date(8.64e15)));
}

// nutrition_scope._source_plan: an entry's own recipe, or for leftovers the source's, following the chain
function planOf(entry) {
  const seen = {};
  let current = entry;
  for (let hop = 0; hop <= 5 && current; hop++) {
    if (current.references) return current.references;
    const source = current.consumesLeftoverFrom;
    if (!source || seen[source.id]) return null;
    seen[source.id] = true;
    current = source;
  }
  return null;
}

// nutrition_scope.entry_servings_eaten: [servings, whether the default was assumed]
function servingsEaten(holder) {
  const q = holder.hasPlannedConsumption;
  if (q && q.value != null && q.value >= 0 && q.unit === "servings") return [q.value, false];
  return [1.0, true];
}

// nutrition_scope.eaten_by_no_one: a dish made at a prep session, eaten later as leftovers
const eatenByNoOne = (entry) => !(entry.hasShare || []).length && !servingsEaten(entry)[1] && servingsEaten(entry)[0] <= 0;

// nutrition_scope.entry_person_servings
function personServings(entry, person) {
  const shares = entry.hasShare || [];
  if (!shares.length) return servingsEaten(entry);
  let total = 0, assumed = false;
  for (const share of shares) {
    if (share.eatenBy && share.eatenBy.id === person.id) {
      const [servings, was] = servingsEaten(share);
      total += servings;
      assumed = assumed || was;
    }
  }
  return [total, assumed];
}

// nutrition_scope.stored_figure: a recipe's stored nutrition per serving (J28), in `unit`.
// {amount, trusted, estimated, reason}; amount null when unknown. null when nothing is stored, where
// Python would work the figure out from the ingredients: tools/calculate_recipe_nutrition.py stores it.
const USABLE = ["sourced", "estimated", "calculated"];
const storedByPlan = {};               // a recipe's stored figures by nutrient id, read once per page
function storedOf(plan) {
  if (!storedByPlan[plan.id]) {
    const byNutrient = {};
    for (const p of plan.servingProfiles || []) {
      if (p.basis !== "per_serving" || !p.forNutrient) continue;
      (byNutrient[p.forNutrient.id] = byNutrient[p.forNutrient.id] || []).push(p);
    }
    storedByPlan[plan.id] = byNutrient;
  }
  return storedByPlan[plan.id];
}
function servingFigure(plan, nutrientId, unit) {
  const rows = storedOf(plan)[nutrientId] || [];
  if (rows.length !== 1) return null;
  const p = rows[0];
  if (p.amount == null) return {amount: null, trusted: false, estimated: false, reason: p.source || "unknown"};
  const amount = convertNutrient(p.amount, p.unit, unit);
  if (amount == null) return {amount: null, trusted: false, estimated: false, reason: "stored in " + p.unit + ", not comparable with " + unit};
  return {amount: amount, trusted: USABLE.indexOf(p.provenance) >= 0, estimated: p.provenance === "estimated",
          reason: p.provenance === "calculated" ? null : p.source};
}

// The day boundary of a MealPlan's daily targets, for laying its entries out by day
function weekZone(mealPlan) {
  for (const c of mealPlan.hasConstraint || []) {
    const zone = c.type === "NutritionTarget" ? zoneOf(c.dayBoundaryRule) : null;
    if (zone) return zone;
  }
  return "UTC";
}


// The MealPlans with entries, the latest first by the start of their region
function weeksWithEntries() {
  return $.find("MealPlan").filter((m) => (m.hasEntry || []).length)
    .sort((a, b) => new Date((b.isAbout && b.isAbout.hasBeginning) || 0) - new Date((a.isAbout && a.isAbout.hasBeginning) || 0));
}

// The caller's one household, or null (the superuser, or someone in none or several)
function callerHousehold() {
  const households = (($.me && $.me.groups) || []).filter((g) => g.type === "Household");
  return households.length === 1 ? households[0] : null;
}

// The week a method's caller asks about: a MealPlan they may read, and for a member of a household,
// their household's own (as for its bookings: a week every signed-in user sees is no household's).
// {week} or {problem}
function callerWeek(id) {
  const found = $.find("MealPlan", {id: String(id || "")});
  const week = Array.isArray(found) ? found[0] : found;
  if (!week || week.type !== "MealPlan") return {problem: "no such week"};
  if (callerHousehold() && week.visibleToAuthenticatedUsers !== false) return {problem: week.name + ": not your household's week"};
  return {week: week};
}
