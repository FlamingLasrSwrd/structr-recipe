// bookRequest: a recipe asked for a week, or taken back, for the caller's household, as the recipe
// page's button does (REQUEST_ACTIONS; mealplanner/requests.py), as the caller. A week not planned yet
// is made as the household's MealPlan (forHousehold), private to it.
//
// Arguments: do (ask, withdraw), token, recipe (a RecipeIdentity's id), week (its first day,
// YYYY-MM-DD). Returns {action, problem, process, created, notes}, as the pages record a booking.

return bookForCaller(REQUEST_ACTIONS, $.methodParameters || {});
