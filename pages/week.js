// /structr/html/week[/<MealPlan id>]: a committed week's meals by day, as planning/report.describe_plan
// words a proposed one: what to cook or eat from leftovers, each person's servings, and when to start
// a dish made ahead (data-model.md J29). "Mark cooked" books a cook, as mealplanner/pantry.cook does;
// "Skip" and "Undo" change the menu as the week goes, as mealplanner/menu_changes.py does. The bookings
// themselves are in pages/lib/70_menu.js (WEEK_ACTIONS), shared with the bookWeek method.

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
