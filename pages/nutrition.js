// /structr/html/nutrition[/<MealPlan id>]: every target of a committed week judged at its own scope, per
// person, as nutrition_scope.nutrition_report does: a day's total is the person's baseline and their
// share of each meal that day, from each recipe's stored figure per serving (J28). The report itself is
// pages/lib/80_nutrition.js (report, weekTotals), which the nutritionReport method returns.

const WORDS = {ok: "met", below_min: "under", above_max: "over", indeterminate: "unknown", unsupported: "not judged"};
const rangeWords = (r) => (r.min != null && r.max != null ? number(r.min, 0) + "–" + number(r.max, 0)
  : r.min != null ? "at least " + number(r.min, 0) : r.max != null ? "at most " + number(r.max, 0) : "any") + " " + r.unit;
const rangeText = (r) => esc(rangeWords(r));
// a total that rests on an estimate somewhere (J21) is marked ≈ and says which meals (REVIEW.md round 3, #12)
const ESTIMATE = "≈";
const estimates = (r) => (r.estimated && r.estimated.length ? "; rests on estimates: " + r.estimated.join(", ") : "");
const mark = (r) => (r.estimated && r.estimated.length ? ESTIMATE : "");
const cell = (r) => "<td class=\"" + r.status + "\" title=\"" + esc(WORDS[r.status] + (r.unknown && r.unknown.length ? ": no figure for " + r.unknown.join(", ") : "") + estimates(r)) + "\">"
  + (r.status === "unsupported" ? "–" : mark(r) + number(r.total, r.total >= 100 ? 0 : 1)) + "</td>";

// the week's total of a daily target: its range over the days judged, and how many days were each
function weekCell(t) {
  const range = rangeWords({min: t.week_min, max: t.week_max, unit: t.unit});
  const days = ["ok", "below_min", "above_max", "indeterminate"].filter((s) => t.day_statuses[s])
    .map((s) => t.day_statuses[s] + " " + WORDS[s]).join(", ");
  const why = WORDS[t.status] + " for the week: " + range + " over " + t.days + (t.days === 1 ? " day" : " days") + "; days: " + days
    + (t.unknown.length ? "; no figure for " + t.unknown.join(", ") : "") + estimates(t);
  return "<td class=\"" + t.status + " total\" title=\"" + esc(why) + "\">" + mark(t) + number(t.total, t.total >= 100 ? 0 : 1)
    + " <small>" + esc(WORDS[t.status]) + "</small></td>";
}

function table(rows, columns, label, totals) {
  const byTarget = {};
  for (const r of rows) (byTarget[r.target] = byTarget[r.target] || []).push(r);
  let html = "<table><thead><tr><th>Target</th><th>Range</th>" + columns.map((c) => "<th>" + esc(label(c)) + "</th>").join("")
    + (totals ? "<th class=\"total\">Week</th>" : "") + "</tr></thead><tbody>";
  for (const name of Object.keys(byTarget).sort((a, b) => byTarget[a][0].nutrient.localeCompare(byTarget[b][0].nutrient))) {
    const first = byTarget[name][0];
    html += "<tr><td>" + esc(first.nutrient) + (first.hard ? " <span class=\"hard\">hard</span>" : "") + "</td><td>" + rangeText(first) + "</td>"
      + columns.map((c) => { const r = byTarget[name].find((x) => x.group === c); return r ? cell(r) : "<td></td>"; }).join("")
      + (totals ? (totals[name] ? weekCell(totals[name]) : "<td></td>") : "") + "</tr>";
  }
  return html + "</tbody></table>";
}

const week = chosenWeek();
let html = nav("nutrition") + "<h1>Nutrition</h1>";
let data = [];
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  const rows = report(week), totals = weekTotals(rows);
  data = rows.concat(totals);
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("nutrition", week)
    + "<p class=\"note\">Each day: the baseline and the person's share of every meal, from stored figures per serving. "
    + "<span class=\"ok\">met</span> <span class=\"below_min\">under</span> <span class=\"above_max\">over</span> "
    + "<span class=\"indeterminate\">unknown</span>; " + ESTIMATE + " rests on an estimate somewhere; hover a cell for why. "
    + "Week: a daily target's days added up, against its range times the days with meals.</p>";
  const people = Array.from(new Set(rows.map((r) => r.person))).sort((a, b) => String(a).localeCompare(String(b)));
  for (const person of people) {
    const mine = rows.filter((r) => r.person === person);
    html += "<h3>" + esc(person || "Everyone") + "</h3>";
    const daily = mine.filter((r) => r.scope === "daily" && r.group);
    const days = Array.from(new Set(daily.map((r) => r.group))).sort();
    const mineTotals = {};
    for (const t of totals) if (t.person === person) mineTotals[t.target] = t;
    if (days.length) html += table(daily, days, (d) => dayLabel(new Date(d + "T12:00:00Z"), "UTC"), mineTotals);
    const weekly = mine.filter((r) => r.scope === "weekly" && r.group);
    if (weekly.length) html += "<h4>The whole week</h4>" + table(weekly, ["week"], () => "Week");
    const meals = mine.filter((r) => r.scope === "per_meal" && r.group);
    if (meals.length) {
      html += "<h4>Each meal</h4><table><thead><tr><th>Target</th><th>Range</th><th>Met</th><th>Under</th><th>Over</th><th>Unknown</th></tr></thead><tbody>";
      for (const name of Array.from(new Set(meals.map((r) => r.target))).sort()) {
        const rs = meals.filter((r) => r.target === name);
        html += "<tr><td>" + esc(rs[0].nutrient) + "</td><td>" + rangeText(rs[0]) + "</td>"
          + ["ok", "below_min", "above_max", "indeterminate"].map((s) => "<td>" + rs.filter((r) => r.status === s).length + "</td>").join("") + "</tr>";
      }
      html += "</tbody></table>";
    }
    const odd = mine.filter((r) => r.status === "unsupported");
    if (odd.length) html += "<p class=\"note\">Not judged: " + odd.map((r) => esc(r.target)).join(", ") + ".</p>";
  }
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
