// A week's nutrition judged against every target at its own scope, per person
// (nutrition_scope.nutrition_report, week_totals): the nutrition page, and the nutritionReport method.

// nutrition_scope._status: over a maximum is definite even with an unknown, since totals only grow
function status(total, unknown, min, max) {
  if (max != null && total > max) return "above_max";
  if (unknown) return "indeterminate";
  if (min != null && total < min) return "below_min";
  return "ok";
}

// nutrition_scope.baseline_day_figures: [per day, the baseline recipes with no figure, those resting on an estimate]
function baselineDay(holder, nutrientId, unit) {
  let total = 0;
  const unknown = [], estimated = [];
  for (const plan of holder.hasBaseline || []) {
    const figure = servingFigure(plan, nutrientId, unit);
    if (!figure || figure.amount == null) unknown.push(plan.name);
    else {
      total += figure.amount;
      if (figure.estimated) estimated.push(plan.name);
    }
  }
  return [total, unknown, estimated];
}

// nutrition_scope.entry_nutrient_figure: {amount, estimated}, by everyone or by one person; amount null when unknown
function intakeFigure(entry, nutrientId, unit, person) {
  let servings;
  if (person) {
    servings = personServings(entry, person)[0];
    if (servings === 0) return {amount: 0, estimated: false};
  } else {
    servings = servingsEaten(entry)[0];
  }
  const plan = planOf(entry);
  const figure = plan ? servingFigure(plan, nutrientId, unit) : null;
  return figure && figure.amount != null ? {amount: figure.amount * servings, estimated: figure.estimated}
    : {amount: null, estimated: false};
}

// nutrition_scope.entry_nutrient_intake: by everyone, or by one person; null when unknown
function intake(entry, nutrientId, unit, person) {
  return intakeFigure(entry, nutrientId, unit, person).amount;
}

// nutrition_scope.nutrition_report: one row per (target, group); a group is a meal, a day or the week
function report(week) {
  // a skipped meal with something not in the book eaten instead: in its groups with no figure
  const instead = (week.hasEntry || []).filter((e) => e.isSkipped && e.eatenInstead);
  const entries = activeEntries(week).filter((e) => !eatenByNoOne(e)).concat(instead);
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
    const [perDay, baselineUnknown, baselineEstimated] = (holder.hasBaseline || []).length && scope !== "per_meal"
      ? baselineDay(holder, nutrient.id, range.unit) : [0, [], []];
    for (const key of Object.keys(groups).sort()) {
      const days = scope === "daily" ? 1
        : new Set(groups[key].map(startOf).filter(Boolean).map((s) => dayKey(s, zone || "UTC"))).size;
      let total = scope !== "per_meal" ? perDay * days : 0;
      const unknown = baselineUnknown.map((name) => name + " (baseline)");
      const estimated = baselineEstimated.map((name) => name + " (baseline)");
      for (const entry of groups[key]) {
        if (entry.isSkipped) {
          if (!target.forPerson || personServings(entry, target.forPerson)[0] > 0) unknown.push(entry.name + " (" + entry.eatenInstead + " instead)");
          continue;
        }
        const figure = intakeFigure(entry, nutrient.id, range.unit, target.forPerson);
        if (figure.amount == null) unknown.push(entry.name);
        else {
          total += figure.amount;
          if (figure.estimated && figure.amount > 0) estimated.push(entry.name);
        }
      }
      rows.push(Object.assign({}, base, {group: key, total: total, unknown: unknown, estimated: estimated,
                                         status: status(total, unknown.length > 0, range.minValue, range.maxValue)}));
    }
  }
  return rows;
}

// nutrition_scope.week_totals: each daily target's days added up, judged against its range times the days judged
function weekTotals(rows) {
  const byTarget = {};
  for (const r of rows) if (r.scope === "daily" && r.group != null) (byTarget[r.target] = byTarget[r.target] || []).push(r);
  return Object.keys(byTarget).map((name) => {
    const days = byTarget[name], first = days[0], n = days.length;
    const weekMin = first.min == null ? null : first.min * n, weekMax = first.max == null ? null : first.max * n;
    const total = days.reduce((s, r) => s + r.total, 0);
    const unknown = Array.from(new Set([].concat.apply([], days.map((r) => r.unknown))));
    const estimated = Array.from(new Set([].concat.apply([], days.map((r) => r.estimated))));
    const counted = {};
    for (const r of days) counted[r.status] = (counted[r.status] || 0) + 1;
    return Object.assign({}, first, {group: "week", days: n, week_min: weekMin, week_max: weekMax, total: total, unknown: unknown,
                                     estimated: estimated,
                                     day_statuses: counted, status: status(total, unknown.length > 0, weekMin, weekMax)});
  });
}
