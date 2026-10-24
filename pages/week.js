// /structr/html/week[/<MealPlan id>]: a committed week's meals by day, as planning/report.describe_plan
// words a proposed one: what to cook or eat from leftovers, each person's servings, and when to start
// a dish made ahead (data-model.md J29). "Mark cooked" books a cook, as mealplanner/pantry.cook does.

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
    text += entry.fulfilledBy ? " <small class=\"cooked\">cooked</small>"
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

const WEEK_ACTIONS = {
  // pantry.cook
  cook: (booking, r, token) => {
    const found = $.find("MealPlanEntry", {id: String(r.entry || "")});
    const entry = Array.isArray(found) ? found[0] : found;
    if (!entry) throw new BookingError("no such meal");
    if (entry.fulfilledBy) throw new BookingError(entry.name + ": already cooked");
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

const week = chosenWeek();
const data = week ? activeEntries(week).map(datum) : [];
let html = nav("week") + "<h1>Week</h1>" + said;
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const zone = weekZone(week);
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("week", week) + "<p class=\"note\">Times in " + esc(zone) + ".</p>";
  let day = null;
  for (const entry of activeEntries(week)) {
    const start = startOf(entry);
    const key = start ? dayKey(start, zone) : "unplaced";
    if (key !== day) {
      html += (day === null ? "" : "</tbody></table>") + "<h3>" + (start ? esc(dayLabel(start, zone)) : "No time set") + "</h3>"
        + "<table><thead><tr><th>Time</th><th>Meal</th><th>What</th><th>Servings eaten</th></tr></thead><tbody>";
      day = key;
    }
    html += "<tr><td>" + (start ? esc(clock(start, zone)) : "") + "</td><td>" + esc(mealOf(entry)) + "</td><td>" + what(entry, zone)
      + "</td><td>" + eaters(entry) + "</td></tr>";
  }
  html += day === null ? "<p>This week has no meals.</p>" : "</tbody></table>";
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
