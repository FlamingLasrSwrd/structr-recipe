// /structr/html/nutrition[/<MealPlan id>]: every target of a committed week judged at its own scope, per
// person, as nutrition_scope.nutrition_report does: a day's total is the person's baseline and their
// share of each meal that day, from each recipe's stored figure per serving (J28).

// nutrition_scope._status: over a maximum is definite even with an unknown, since totals only grow
function status(total, unknown, min, max) {
  if (max != null && total > max) return "above_max";
  if (unknown) return "indeterminate";
  if (min != null && total < min) return "below_min";
  return "ok";
}

// nutrition_scope.baseline_day_intake: [per day, the baseline recipes with no figure]
function baselineDay(holder, nutrientId, unit) {
  let total = 0;
  const unknown = [];
  for (const plan of holder.hasBaseline || []) {
    const figure = servingFigure(plan, nutrientId, unit);
    if (!figure || figure.amount == null) unknown.push(plan.name);
    else total += figure.amount;
  }
  return [total, unknown];
}

// nutrition_scope.entry_nutrient_intake: by everyone, or by one person; null when unknown
function intake(entry, nutrientId, unit, person) {
  let servings;
  if (person) {
    servings = personServings(entry, person)[0];
    if (servings === 0) return 0;
  } else {
    servings = servingsEaten(entry)[0];
  }
  const plan = planOf(entry);
  const figure = plan ? servingFigure(plan, nutrientId, unit) : null;
  return figure && figure.amount != null ? figure.amount * servings : null;
}

// nutrition_scope.nutrition_report: one row per (target, group); a group is a meal, a day or the week
function report(week) {
  const entries = activeEntries(week);
  const rows = [];
  for (const target of (week.hasConstraint || []).filter((c) => c.type === "NutritionTarget")) {
    const nutrient = target.forNutrient, range = target.hasTargetRange;
    if (!nutrient || !range) continue;
    const scope = target.hasTimeScope, zone = zoneOf(target.dayBoundaryRule);
    const base = {target: target.name, nutrient: nutrient.name, scope: scope, hard: target.strictness === "hard",
                  min: range.minValue, max: range.maxValue, unit: range.unit, person: target.forPerson ? target.forPerson.name : null};
    if (["per_meal", "daily", "weekly"].indexOf(scope) < 0 || (scope === "daily" && !zone)
        || !NUTRIENT_UNITS[String(range.unit || "").trim().toLowerCase()]) {
      rows.push(Object.assign({}, base, {group: null, status: "unsupported"}));      // target_scope_problem
      continue;
    }
    const groups = {};
    for (const entry of entries) {
      let key;
      if (scope === "per_meal") key = entry.name;
      else if (scope === "weekly") key = "week";
      else {
        const start = startOf(entry);
        if (!start) continue;
        key = dayKey(start, zone);
      }
      (groups[key] = groups[key] || []).push(entry);
    }
    const holder = target.forPerson || week;                                         // whose baseline
    const [perDay, baselineUnknown] = (holder.hasBaseline || []).length && scope !== "per_meal"
      ? baselineDay(holder, nutrient.id, range.unit) : [0, []];
    for (const key of Object.keys(groups).sort()) {
      const days = scope === "daily" ? 1
        : new Set(groups[key].map(startOf).filter(Boolean).map((s) => dayKey(s, zone || "UTC"))).size;
      let total = scope !== "per_meal" ? perDay * days : 0;
      const unknown = baselineUnknown.map((name) => name + " (baseline)");
      for (const entry of groups[key]) {
        const amount = intake(entry, nutrient.id, range.unit, target.forPerson);
        if (amount == null) unknown.push(entry.name);
        else total += amount;
      }
      rows.push(Object.assign({}, base, {group: key, total: total, unknown: unknown,
                                         status: status(total, unknown.length > 0, range.minValue, range.maxValue)}));
    }
  }
  return rows;
}

const WORDS = {ok: "met", below_min: "under", above_max: "over", indeterminate: "unknown", unsupported: "not judged"};
const rangeText = (r) => (r.min != null && r.max != null ? number(r.min, 0) + "–" + number(r.max, 0)
  : r.min != null ? "at least " + number(r.min, 0) : r.max != null ? "at most " + number(r.max, 0) : "any") + " " + esc(r.unit);
const cell = (r) => "<td class=\"" + r.status + "\" title=\"" + esc(WORDS[r.status] + (r.unknown && r.unknown.length ? ": no figure for " + r.unknown.join(", ") : "")) + "\">"
  + (r.status === "unsupported" ? "–" : number(r.total, r.total >= 100 ? 0 : 1)) + "</td>";

function table(rows, columns, label) {
  const byTarget = {};
  for (const r of rows) (byTarget[r.target] = byTarget[r.target] || []).push(r);
  let html = "<table><thead><tr><th>Target</th><th>Range</th>" + columns.map((c) => "<th>" + esc(label(c)) + "</th>").join("") + "</tr></thead><tbody>";
  for (const name of Object.keys(byTarget).sort((a, b) => byTarget[a][0].nutrient.localeCompare(byTarget[b][0].nutrient))) {
    const first = byTarget[name][0];
    html += "<tr><td>" + esc(first.nutrient) + (first.hard ? " <span class=\"hard\">hard</span>" : "") + "</td><td>" + rangeText(first) + "</td>"
      + columns.map((c) => { const r = byTarget[name].find((x) => x.group === c); return r ? cell(r) : "<td></td>"; }).join("") + "</tr>";
  }
  return html + "</tbody></table>";
}

const week = chosenWeek();
let html = nav("nutrition") + "<h1>Nutrition</h1>";
let data = [];
if (!week) {
  html += "<p>No week has been committed yet: <code>tools/plan_week.py --commit</code> writes one.</p>";
} else {
  data = report(week);
  html += "<h2>" + esc(week.name) + "</h2>" + weekPicker("nutrition", week)
    + "<p class=\"note\">Each day: the baseline and the person's share of every meal, from stored figures per serving. "
    + "<span class=\"ok\">met</span> <span class=\"below_min\">under</span> <span class=\"above_max\">over</span> "
    + "<span class=\"indeterminate\">unknown</span>; hover a cell for why.</p>";
  const people = Array.from(new Set(data.map((r) => r.person))).sort((a, b) => String(a).localeCompare(String(b)));
  for (const person of people) {
    const mine = data.filter((r) => r.person === person);
    html += "<h3>" + esc(person || "Everyone") + "</h3>";
    const daily = mine.filter((r) => r.scope === "daily" && r.group);
    const days = Array.from(new Set(daily.map((r) => r.group))).sort();
    if (days.length) html += table(daily, days, (d) => dayLabel(new Date(d + "T12:00:00Z"), "UTC"));
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
