// shoppingList: what a committed week's meals not yet cooked still need, less eligible stock, by the
// day each food is first needed, with a cost at a price level, as the shopping page lists it
// (shoppingFor; mealplanner/shopping.py). For a member of a household, only their household's own
// stock counts against the need.
//
// Arguments: week (a MealPlan's id; for a member of a household, their household's own), prices (a
// price level, default "Home prices"). Returns {week, priced, cooks, leftovers, buy, covered,
// unquantified, not_bought, unpriced, total} (a line's `first` an ISO time) or {problem}.

const asked = $.methodParameters || {};
const chosen = callerWeek(asked.week);
let answer = chosen;
if (!chosen.problem) {
  const list = shoppingFor(chosen.week, String(asked.prices || "Home prices"), callerHousehold() != null);
  const line = (l) => Object.assign({}, l, {first: l.first ? l.first.toISOString() : null});
  answer = {week: chosen.week.name, priced: list.priced, cooks: list.cooks, leftovers: list.leftovers,
            buy: list.buy.map(line), covered: list.covered.map(line), unquantified: list.unquantified,
            not_bought: list.not_bought.slice().sort(), unpriced: list.unpriced.slice().sort(), total: list.total};
}
return answer;
