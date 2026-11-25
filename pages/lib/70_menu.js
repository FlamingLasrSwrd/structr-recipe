// A week's meals cooked and changed as the week goes (mealplanner/pantry.py cook, menu_changes.py):
// the week page's forms, and the bookWeek method.

// inventory.eligible_lots, with no policy filters: a food's positive, unexpired stock, of it or a
// food below it, soonest to expire first (unknown last), then by name; a household's own stock only
// (ownStock), when a household books
function eligibleLots(food, booking) {
  const types = subtypesOf(food), lots = [];
  for (const portion of $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))) {
    if (!portion.instanceOf || !types[portion.instanceOf.id] || !ownStock(booking, portion)) continue;
    const level = onHand(portion);
    if (!Array.isArray(level) || !(level[0] > 0)) continue;
    const [days] = daysUntilExpiry(portion);
    if (days != null && days < 0) continue;
    lots.push({portion: portion, grams: level[0], days: days});
  }
  const byName = (a, b) => (a.portion.name < b.portion.name ? -1 : a.portion.name > b.portion.name ? 1 : 0);
  return lots.sort((a, b) => (a.days == null) - (b.days == null) || ((a.days || 0) - (b.days || 0)) || byName(a, b));
}

// nutrition_scope.raw_inputs: [step, spec] for each ingredient the recipe buys, not optional
function rawInputs(plan) {
  const pairs = [].concat(...(plan.steps || []).map((step) => (step.hasSpecification || []).map((spec) => [step, spec])));
  const produced = {};
  for (const [, spec] of pairs) if (spec.hasParticipationRole === "output" && spec.specifies) produced[spec.specifies.id] = true;
  return pairs.filter(([, spec]) => spec.hasParticipationRole === "input" && spec.specifies && !produced[spec.specifies.id] && !spec.isOptional);
}


// menu_changes.book_recipe: a version by its full name, or a recipe's newest version, ignoring case
function bookRecipe(text) {
  const wanted = String(text || "").trim().toLowerCase();
  if (!wanted) return null;
  const plans = $.find("Plan").filter((p) => p.specializationOf);
  const exact = plans.find((p) => String(p.name).toLowerCase() === wanted);
  if (exact) return exact;
  let best = null, newest = -1;
  for (const p of plans) {
    const m = /^(.*) v(\d+)$/.exec(String(p.name));
    if (m && m[1].toLowerCase() === wanted && Number(m[2]) > newest) { best = p; newest = Number(m[2]); }
  }
  return best;
}

// menu_changes._ensure: find by name, else create; an existing node gets `props`
function ensureWith(booking, type, name, props) {
  const before = booking.created.length;
  const node = ensureNode(booking, type, name, props);
  if (booking.created.length === before) for (const key of Object.keys(props)) node[key] = props[key];
  return node;
}

// menu_changes._held: another meal of the week at this one's time, not skipped
function heldBy(entry) {
  const start = startOf(entry);
  if (!entry.memberOf || !start) return null;
  const other = (entry.memberOf.hasEntry || []).find((e) => e.id !== entry.id && !e.isSkipped && startOf(e) && startOf(e).getTime() === start.getTime());
  return other ? other.name : null;
}

// What a booking's words call a meal: "<day and meal> (<recipe>)" for planning/commit.py's "<slot key> -- <recipe>"
function mealWords(entryOrName) {
  const name = String(entryOrName && entryOrName.name != null ? entryOrName.name : entryOrName || "");
  const parts = name.split(" -- ");
  return parts.length > 1 ? parts[0] + " (" + parts.slice(1).join(" -- ") + ")" : name;
}
const NO_MEAL = "that meal isn't in this week any more. Reload the page to see what is";
const NOT_OUR_WEEK = " is not in your household's week, so it can't be changed here";

// menu_changes._replacement: a cook of `plan` at the skipped meal, for the same people and servings
function replacement(booking, entry, plan) {
  const name = String(entry.name).split(" -- ")[0] + " -- " + plan.name;
  if (name === entry.name) throw new BookingError(plan.name + " is the meal being skipped, so it can't be what was eaten instead");
  for (const there of $.find("MealPlanEntry", {name: name})) {
    if (booking.household && there.visibleToAuthenticatedUsers !== false) continue;     // ensureNode's own nodes
    if (there.memberOf && entry.memberOf && there.memberOf.id !== entry.memberOf.id) {
      throw new BookingError(plan.name + " is planned at this meal in another week already (" + there.memberOf.name + ")");
    }
  }
  const region = entry.isAbout, shares = entry.hasShare || [];
  const eaten = shares.length ? shares.reduce((s, x) => s + servingsEaten(x)[0], 0) : servingsEaten(entry)[0];
  const props = {memberOf: entry.memberOf, isSkipped: false, references: plan, hasPlannedServings: eaten,
                 consumesLeftoverFrom: null, eatenInstead: null, hasPlannedConsumption: null,
                 isAbout: ensureWith(booking, "TemporalRegion", name + " region", {
                   hasBeginning: region && region.hasBeginning ? stamp(new Date(region.hasBeginning)) : null,
                   hasEnd: region && region.hasEnd ? stamp(new Date(region.hasEnd)) : null})};
  if (Math.abs(eaten - 1) > 1e-9) props.hasPlannedConsumption = ensureWith(booking, "QuantitySpecification", name + " servings eaten",
                                                                           {value: eaten, unit: "servings", status: "specified"});
  const made = ensureWith(booking, "MealPlanEntry", name, props);
  for (const share of shares) {
    const who = share.eatenBy ? share.eatenBy.name : "?";
    const qty = ensureWith(booking, "QuantitySpecification", name + " -- " + who + " servings",
                           {value: servingsEaten(share)[0], unit: "servings", status: "specified"});
    ensureWith(booking, "MealShare", name + " -- " + who, {shareOf: made, eatenBy: share.eatenBy, hasPlannedConsumption: qty});
  }
  booking.notes.push("Planned " + plan.name + " in its place, for " + number(eaten, 2) + " serving" + (eaten === 1 ? "" : "s") + ".");
}

// The meal a booking names; a household's own only (ownStock's rule, for its week)
function entryNamed(r, booking) {
  const found = $.find("MealPlanEntry", {id: String(r.entry || "")});
  const entry = Array.isArray(found) ? found[0] : found;
  if (!entry || entry.type !== "MealPlanEntry") throw new BookingError(NO_MEAL);
  if (booking.household && entry.visibleToAuthenticatedUsers !== false) throw new BookingError(mealWords(entry) + NOT_OUR_WEEK);
  return entry;
}

const WEEK_ACTIONS = {
  // menu_changes.skip
  skip: (booking, r) => {
    const entry = entryNamed(r, booking);
    if (entry.isSkipped) throw new BookingError(mealWords(entry) + " is skipped already");
    if (entry.fulfilledBy) throw new BookingError(mealWords(entry) + " was cooked already, so it can't be skipped. Skip the meals that were to eat its leftovers instead");
    const instead = String(r.instead || "").split(/\s+/).filter((w) => w).join(" ");
    const plan = instead ? bookRecipe(instead) : null;
    if (plan) replacement(booking, entry, plan);
    entry.isSkipped = true;
    entry.eatenInstead = instead && !plan ? instead : null;
    booking.notes.push(instead && !plan ? "Skipped " + mealWords(entry) + ", with " + instead + " eaten instead. "
                                          + "That isn't in the recipe book, so the day's nutrition is unknown."
                                        : "Skipped " + mealWords(entry) + ".");
    const pending = (entry.sourceForLeftoverEntries || []).slice();
    while (pending.length) {
      const later = pending.shift();
      if (later.isSkipped) continue;
      later.isSkipped = true;
      booking.notes.push("Also skipped " + mealWords(later) + ", as there are no leftovers to eat.");
      pending.push(...(later.sourceForLeftoverEntries || []));
    }
  },
  // menu_changes.unskip
  unskip: (booking, r) => {
    const entry = entryNamed(r, booking);
    if (!entry.isSkipped) throw new BookingError(mealWords(entry) + " isn't skipped");
    const source = entry.consumesLeftoverFrom;
    if (source && source.isSkipped) throw new BookingError(mealWords(entry) + " eats the leftovers of " + mealWords(source) + ", which is skipped. Undo that one first");
    const held = heldBy(entry);
    if (held) throw new BookingError(mealWords(held) + " is planned at this meal now. Skip it first");
    entry.isSkipped = false;
    entry.eatenInstead = null;
    booking.notes.push("Planned " + mealWords(entry) + " again.");
    const pending = (entry.sourceForLeftoverEntries || []).slice();
    while (pending.length) {
      const later = pending.shift();
      if (!later.isSkipped || later.eatenInstead) continue;
      const there = heldBy(later);
      if (there) { booking.notes.push("Left " + mealWords(later) + " skipped, as " + mealWords(there) + " is planned there now."); continue; }
      later.isSkipped = false;
      booking.notes.push("Also planned " + mealWords(later) + " again.");
      pending.push(...(later.sourceForLeftoverEntries || []));
    }
  },

  // pantry.cook
  cook: (booking, r, token) => {
    const entry = entryNamed(r, booking);
    if (entry.fulfilledBy) throw new BookingError(mealWords(entry) + " is already cooked");
    if (entry.isSkipped) throw new BookingError(mealWords(entry) + " is skipped, so it can't be cooked. Undo the skip first");
    const plan = entry.references;
    if (!plan || entry.hasPlannedServings == null) throw new BookingError(mealWords(entry) + " is leftovers, which take nothing from the pantry");
    const y = plan.hasRecipeYield;
    if (!y || y.unit !== "servings" || !y.value) throw new BookingError(plan.name + " doesn't say how many servings it makes, so how much to take can't be worked out");
    const scale = entry.hasPlannedServings / y.value;
    const process = bookProcess(booking, null, "Cook " + token + " -- " + plan.name, NOW, {concretizes: plan});
    const inputs = rawInputs(plan), stock = {}, taken = {}, drawn = {};
    // as pantry.cook: the stock before any draw, and each later draw of a food from one portion numbered
    for (const [, spec] of inputs) if (!stock[spec.specifies.id]) stock[spec.specifies.id] = eligibleLots(spec.specifies, booking);
    for (const [, spec] of inputs) {
      const food = spec.specifies, q = spec.hasSpecifiedQuantity;
      const grams = q && q.value ? toGrams(food, q.value, q.unit) : null;
      if (!grams) { booking.notes.push("The recipe gives no amount of " + food.name + ", so none was taken from the pantry."); continue; }
      const need = grams * scale;
      let left = need;
      for (const lot of stock[food.id]) {
        if (left <= 1e-9) break;
        const id = lot.portion.id, free = lot.grams - (taken[id] || 0);
        if (free <= 1e-9) continue;
        const take = Math.min(left, free);
        let label = food.name + " from " + lot.portion.name;
        drawn[label] = (drawn[label] || 0) + 1;
        if (drawn[label] > 1) label += " #" + drawn[label];
        bookDraw(booking, process, lot.portion, take, NOW, label, spec);
        taken[id] = (taken[id] || 0) + take;
        left -= take;
      }
      if (left > 1e-6) booking.notes.push("Not in the pantry: " + number(left, 0) + " g of the " + number(need, 0) + " g of " + food.name + " it took.");
    }
    // as pantry.cook: a draw that leaves some of a sealed portion opens it, as a use does; a whole item is left be
    for (const id of Object.keys(stock)) {
      for (const lot of stock[id]) {
        const had = taken[lot.portion.id] || 0;
        if (!(had > 0 && had < lot.grams - 1e-9)) continue;
        if (lot.portion.type === "PortionOfSubstance") openedByUse(booking, lot.portion);
        delete taken[lot.portion.id];             // once, though it is under two foods
      }
    }
    entry.fulfilledBy = process;
  },
};
