// nutritionReport: a week's nutrition, judged against every target at its own scope, per person, as
// the nutrition page shows it (report, weekTotals; nutrition_scope.nutrition_report): a row per target
// and group (a meal, a day, the week), then each daily target's days added up.
//
// Arguments: week (a MealPlan's id; for a member of a household, their household's own). Returns
// {week, rows} or {problem}.

const chosen = callerWeek(($.methodParameters || {}).week);
let answer = chosen;
if (!chosen.problem) {
  const rows = report(chosen.week);
  answer = {week: chosen.week.name, rows: rows.concat(weekTotals(rows))};
}
return answer;
