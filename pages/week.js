// /structr/html/week[/<MealPlan id>]: a committed week's meals by day, as planning/report.describe_plan
// words a proposed one: what to cook or eat from leftovers, each person's servings, and when to start
// a dish made ahead (data-model.md J29). "Mark cooked" books a cook, as mealplanner/pantry.cook does;
// "Skip" and "Undo" change the menu as the week goes, as mealplanner/menu_changes.py does.

const recipeLink = (plan) => plan ? "<a href=\"/structr/html/recipe/" + plan.id + "\">" + esc(plan.name) + "</a>" : "?";

// The meal an entry is for: planning/commit.py names it "<slot key> -- <recipe>", the slot key
// ending in its meal type ("Tue 06 Oct Breakfast")
function mealOf(entry) {
  const key = String(entry.name || "").split(" -- ")[0].trim();
  return key.split(" ").pop() || key;
}

function eaters(entry) {
  const shares = entry.hasShare || [];
  if (!shares.length) return number(servingsEaten(entry)[0], 2);
  return shares.slice().sort((a, b) => String(a.eatenBy && a.eatenBy.name).localeCompare(String(b.eatenBy && b.eatenBy.name)))
    .map((s) => esc(s.eatenBy ? s.eatenBy.name : "?") + " " + number(servingsEaten(s)[0], 2)).join(", ");
}

function what(entry, zone) {
  const plan = planOf(entry);
  if (entry.references) {
    let text = "Cook " + recipeLink(plan) + " for " + number(entry.hasPlannedServings, 2) + " serving" + (entry.hasPlannedServings === 1 ? "" : "s");
    text += entry.fulfilledBy ? " <small class=\"cooked\">cooked</small>" : entry.isSkipped ? ""
      : " <form class=\"inline\" action=\"/structr/html/week/" + esc(entry.memberOf ? entry.memberOf.id : "") + "\">"
        + "<input type=\"hidden\" name=\"do\" value=\"cook\"><input type=\"hidden\" name=\"entry\" value=\"" + esc(entry.id) + "\">"
        + "<input type=\"hidden\" name=\"token\" value=\"" + newToken() + "\"><button title=\"Take its ingredients out of the pantry\">Mark cooked</button></form>";
    const start = startOf(entry);
    if (plan && plan.makeAheadHours && start) {
      const by = new Date(start.getTime() - plan.makeAheadHours * 3600e3);
      text += "<div class=\"ahead\">Made ahead: start it by " + esc(whenLabel(by, zone)) + " (" + number(plan.makeAheadHours) + " h before)</div>";
    }
    return text;
  }
  const source = entry.consumesLeftoverFrom;
  if (source) {
    const from = startOf(source);
    return "Leftover " + recipeLink(plan) + " from " + (from ? esc(dayLabel(from, zone)) + " " + esc(mealOf(source)) : esc(source.name));
  }
  return esc(entry.name);
}

// inventory.eligible_lots, with no policy filters: a food's positive, unexpired stock, of it or a
// food below it, soonest to expire first (unknown last), then by name
function eligibleLots(food) {
  const types = subtypesOf(food), lots = [];
  for (const portion of $.find("PortionOfSubstance")) {
    if (!portion.instanceOf || !types[portion.instanceOf.id]) continue;
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

// -- changing the menu as the week goes (mealplanner/menu_changes.py) --------------------------------

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

// menu_changes._replacement: a cook of `plan` at the skipped meal, for the same people and servings
function replacement(booking, entry, plan) {
  const name = String(entry.name).split(" -- ")[0] + " -- " + plan.name;
  if (name === entry.name) throw new BookingError(plan.name + " is the meal skipped");
  const region = entry.isAbout, shares = entry.hasShare || [];
  const eaten = shares.length ? shares.reduce((s, x) => s + servingsEaten(x)[0], 0) : servingsEaten(entry)[0];
  const props = {memberOf: entry.memberOf, isSkipped: false, references: plan, hasPlannedServings: eaten,
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
  booking.notes.push(name + ": planned in its place, for " + number(eaten, 2) + " serving" + (eaten === 1 ? "" : "s") + ".");
}

function entryNamed(r) {
  const found = $.find("MealPlanEntry", {id: String(r.entry || "")});
  const entry = Array.isArray(found) ? found[0] : found;
  if (!entry || entry.type !== "MealPlanEntry") throw new BookingError("no such meal");
  return entry;
}

const WEEK_ACTIONS = {
  // menu_changes.skip
  skip: (booking, r) => {
    const entry = entryNamed(r);
    if (entry.isSkipped) throw new BookingError(entry.name + ": skipped already");
    if (entry.fulfilledBy) throw new BookingError(entry.name + ": cooked already, so it happened; skip the meals that were to eat it instead");
    const instead = String(r.instead || "").split(/\s+/).filter((w) => w).join(" ");
    const plan = instead ? bookRecipe(instead) : null;
    if (plan) replacement(booking, entry, plan);
    entry.isSkipped = true;
    entry.eatenInstead = instead && !plan ? instead : null;
    booking.notes.push(instead && !plan ? entry.name + ": skipped; " + instead + " eaten instead, which the book has no figures for."
                                        : entry.name + ": skipped.");
    const pending = (entry.sourceForLeftoverEntries || []).slice();
    while (pending.length) {
      const later = pending.shift();
      if (later.isSkipped) continue;
      later.isSkipped = true;
      booking.notes.push(later.name + ": skipped too, as there are no leftovers to eat.");
      pending.push(...(later.sourceForLeftoverEntries || []));
    }
  },
  // menu_changes.unskip
  unskip: (booking, r) => {
    const entry = entryNamed(r);
    if (!entry.isSkipped) throw new BookingError(entry.name + ": not skipped");
    const source = entry.consumesLeftoverFrom;
    if (source && source.isSkipped) throw new BookingError(entry.name + ": its leftovers come from " + source.name + ", which is skipped; undo that first");
    const held = heldBy(entry);
    if (held) throw new BookingError(held + " is planned at this meal now; skip it first");
    entry.isSkipped = false;
    entry.eatenInstead = null;
    booking.notes.push(entry.name + ": planned again.");
    const pending = (entry.sourceForLeftoverEntries || []).slice();
    while (pending.length) {
      const later = pending.shift();
      if (!later.isSkipped || later.eatenInstead) continue;
      const there = heldBy(later);
      if (there) { booking.notes.push(later.name + ": left skipped, as " + there + " is planned there now."); continue; }
      later.isSkipped = false;
      booking.notes.push(later.name + ": planned again too.");
      pending.push(...(later.sourceForLeftoverEntries || []));
    }
  },

  // pantry.cook
  cook: (booking, r, token) => {
    const found = $.find("MealPlanEntry", {id: String(r.entry || "")});
    const entry = Array.isArray(found) ? found[0] : found;
    if (!entry) throw new BookingError("no such meal");
    if (entry.fulfilledBy) throw new BookingError(entry.name + ": already cooked");
    if (entry.isSkipped) throw new BookingError(entry.name + ": skipped, so not cooked (undo the skip first)");
    const plan = entry.references;
    if (!plan || entry.hasPlannedServings == null) throw new BookingError(entry.name + ": not a cook (leftovers need nothing from the pantry)");
    const y = plan.hasRecipeYield;
    if (!y || y.unit !== "servings" || !y.value) throw new BookingError(plan.name + ": no yield in servings, so its amounts cannot be scaled");
    const scale = entry.hasPlannedServings / y.value;
    const process = bookProcess(booking, null, "Cook " + token + " -- " + plan.name, NOW, {concretizes: plan});
    for (const [, spec] of rawInputs(plan)) {
      const food = spec.specifies, q = spec.hasSpecifiedQuantity;
      const grams = q && q.value ? toGrams(food, q.value, q.unit) : null;
      if (!grams) { booking.notes.push(food.name + ": no amount in the recipe, so none is drawn."); continue; }
      const need = grams * scale;
      let left = need;
      for (const lot of eligibleLots(food)) {
        if (left <= 1e-9) break;
        const take = Math.min(left, lot.grams);
        bookDraw(booking, process, lot.portion, take, NOW, food.name + " from " + lot.portion.name, spec);
        left -= take;
      }
      if (left > 1e-6) booking.notes.push("Not in the pantry: " + food.name + ", " + number(left, 0) + " g of the " + number(need, 0) + " g it took.");
    }
    entry.fulfilledBy = process;
  },
};

const said = runBooking(WEEK_ACTIONS);

// What the page shows, for tools/check_pages.py
function datum(entry) {
  const plan = planOf(entry), start = startOf(entry);
  const shares = {};
  for (const s of entry.hasShare || []) shares[s.eatenBy ? s.eatenBy.name : "?"] = servingsEaten(s)[0];
  return {entry: entry.name, kind: entry.references ? "cook" : "leftover", recipe: plan ? plan.name : null,
          cooked: entry.references ? entry.hasPlannedServings : null, eaten: servingsEaten(entry)[0], shares: shares,
          start: start ? start.toISOString() : null,
          start_by: entry.references && plan && plan.makeAheadHours && start
            ? new Date(start.getTime() - plan.makeAheadHours * 3600e3).toISOString() : null};
}

// Every meal of the week, a skipped one after the meal planned at its time
function allEntries(mealPlan) {
  const far = new Date(8.64e15);
  return (mealPlan.hasEntry || []).slice()
    .sort((a, b) => ((startOf(a) || far) - (startOf(b) || far)) || ((a.isSkipped ? 1 : 0) - (b.isSkipped ? 1 : 0)));
}

const hidden = (name, value) => "<input type=\"hidden\" name=\"" + name + "\" value=\"" + esc(value) + "\">";

// Skip a meal (saying what was eaten instead), or undo a skip
function changeForm(entry, week) {
  const form = (action) => "<form class=\"inline\" action=\"/structr/html/week/" + esc(week.id) + "\">" + hidden("do", action)
    + hidden("entry", entry.id) + hidden("token", newToken());
  if (entry.isSkipped) return " " + form("unskip") + "<button title=\"Plan this meal again\">Undo</button></form>";
  if (entry.fulfilledBy) return "";
  const start = startOf(entry), past = start && start < NOW;
  return " <details class=\"change\"><summary>" + (past ? "Didn't make it" : "Won't make it") + "</summary>" + form("skip")
    + "<input name=\"instead\" list=\"book\" size=\"28\" placeholder=\"" + (past ? "ate" : "eating") + " instead: a recipe, anything, or nothing\"> "
    + "<button>Skip it</button></form></details>";
}

// The book's recipes, newest version each, for "ate instead"
function bookList() {
  const baselines = new Set([].concat(...$.find("MealPlan").map((m) => m.hasBaseline || []), ...$.find("Person").map((p) => p.hasBaseline || []))
    .map((p) => p.id));
  const names = [];
  for (const identity of $.find("RecipeIdentity").filter((i) => !i.isRetired)) {
    const versions = (identity.planVersions || []).filter((p) => !baselines.has(p.id))
      .sort((a, b) => String(a.name).localeCompare(String(b.name), "en", {numeric: true}));
    if (versions.length) names.push(versions[versions.length - 1].name);
  }
  return "<datalist id=\"book\">" + names.sort().map((n) => "<option value=\"" + esc(n) + "\">").join("") + "</datalist>";
}

const week = chosenWeek();
const data = week ? activeEntries(week).map(datum) : [];
let html = nav("week") + "<h1>Week</h1>" + said;
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const zone = weekZone(week);
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("week", week) + "<p class=\"note\">Times in " + esc(zone) + ".</p>";
  const free = allEntries(week).filter((e) => e.isSkipped && !e.eatenInstead && startOf(e) && startOf(e) > NOW && !heldBy(e));
  if (free.length) html += "<p class=\"note\">" + free.length + " meal" + (free.length === 1 ? " is" : "s are")
    + " free from now on: run <code>tools/plan_week.py</code> with this week's file to plan " + (free.length === 1 ? "it" : "them")
    + ", then <code>--commit</code>.</p>";
  html += bookList();
  let day = null;
  for (const entry of allEntries(week)) {
    const start = startOf(entry);
    const key = start ? dayKey(start, zone) : "unplaced";
    if (key !== day) {
      html += (day === null ? "" : "</tbody></table>") + "<h3>" + (start ? esc(dayLabel(start, zone)) : "No time set") + "</h3>"
        + "<table><thead><tr><th>Time</th><th>Meal</th><th>What</th><th>Servings eaten</th></tr></thead><tbody>";
      day = key;
    }
    const shown = entry.isSkipped ? "<span class=\"skipped\">" + what(entry, zone) + "</span> skipped"
      + (entry.eatenInstead ? "; " + esc(entry.eatenInstead) + " instead" : "") : what(entry, zone);
    html += "<tr" + (entry.isSkipped ? " class=\"skipped\"" : "") + "><td>" + (start ? esc(clock(start, zone)) : "") + "</td><td>"
      + esc(mealOf(entry)) + "</td><td>" + shown + changeForm(entry, week) + "</td><td>" + eaters(entry) + "</td></tr>";
  }
  html += day === null ? "<p>This week has no meals.</p>" : "</tbody></table>";
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
