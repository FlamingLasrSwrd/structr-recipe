// /structr/html/week[/<MealPlan id>]: a committed week's meals by day, as planning/report.describe_plan
// words a proposed one: what to cook or eat from leftovers, each person's servings, and when to start
// a dish made ahead (data-model.md J29).

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
let html = nav("week") + "<h1>Week</h1>";
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
