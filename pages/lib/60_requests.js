// Recipes asked for a week (mealplanner/requests.py): the recipe page's "Cook in the week of ...".

const WEEK_PREFIX = "Week of ";

// requests.week_start: "Week of 2026-10-26" -> "2026-10-26"
function weekStartOf(mealPlan) {
  const m = /^Week of (\d{4}-\d{2}-\d{2})$/.exec(String(mealPlan.name || ""));
  return m ? m[1] : null;
}

const addDays = (day, n) => new Date(new Date(day + "T00:00:00Z").getTime() + n * 86400000).toISOString().slice(0, 10);

// requests.next_week_start: the week after the latest with meals, or once that has begun the first
// on its weekday from today; with none, the coming Monday. Today is the latest week's local day.
function nextWeekStart() {
  const weeks = weeksWithEntries().filter((m) => weekStartOf(m));
  const today = dayKey(NOW, weeks.length ? weekZone(weeks[0]) : "UTC");
  if (!weeks.length) {
    const weekday = (new Date(today + "T00:00:00Z").getUTCDay() + 6) % 7;      // Monday 0, as Python's weekday()
    return addDays(today, (7 - weekday) % 7 || 7);
  }
  let start = addDays(weeks.map(weekStartOf).sort().pop(), 7);
  while (start < today) start = addDays(start, 7);
  return start;
}

// requests._week: the MealPlan named for the week, or null; for a household's booking, its own only
// (ownStock's rule): a week every signed-in user sees is no household's
function weekNamed(start, booking) {
  const found = $.find("MealPlan", {name: WEEK_PREFIX + start})
    .filter((m) => m.type === "MealPlan" && (!booking || !booking.household || m.visibleToAuthenticatedUsers === false));
  if (found.length > 1) throw new BookingError("two MealPlans are named " + WEEK_PREFIX + start);
  return found.length ? found[0] : null;
}

// requests.requested
const requestedIn = (start) => { const w = weekNamed(start); return w ? (w.requestsRecipe || []) : []; };

const weekWords = (start) => new Intl.DateTimeFormat("en-GB", {timeZone: "UTC", weekday: "short", day: "numeric", month: "short"})
  .format(new Date(start + "T12:00:00Z"));

const REQUEST_ACTIONS = {
  // requests.ask
  ask: (booking, r) => {
    const start = String(r.week || ""), recipe = $.find("RecipeIdentity", {id: String(r.recipe || "")});
    const identity = Array.isArray(recipe) ? recipe[0] : recipe;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) throw new BookingError("no week named");
    if (!identity) throw new BookingError("no such recipe");
    const week = weekNamed(start, booking) || ensureNode(booking, "MealPlan", WEEK_PREFIX + start,
                                                booking.household ? {forHousehold: booking.household} : {});
    const current = (week.requestsRecipe || []).slice();
    if (current.some((x) => x.id === identity.id)) { booking.notes.push(identity.name + " was asked for in the week of " + weekWords(start) + " already."); return; }
    week.requestsRecipe = current.concat([identity]);
    booking.notes.push(identity.name + ": asked for in the week of " + weekWords(start) + ".");
  },
  // requests.withdraw
  withdraw: (booking, r) => {
    const start = String(r.week || ""), recipeId = String(r.recipe || "");
    const week = /^\d{4}-\d{2}-\d{2}$/.test(start) ? weekNamed(start, booking) : null;
    const current = week ? (week.requestsRecipe || []).slice() : [];
    const found = current.find((x) => x.id === recipeId);
    if (!found) { booking.notes.push("It was not asked for that week."); return; }
    week.requestsRecipe = current.filter((x) => x.id !== recipeId);
    booking.notes.push(found.name + ": no longer asked for in the week of " + weekWords(start) + ".");
  },
};
