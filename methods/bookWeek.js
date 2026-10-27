// bookWeek: one change to a week's meals for the caller's household, as the week page's forms make
// them (WEEK_ACTIONS; mealplanner/pantry.py cook, menu_changes.py skip and unskip), as the caller:
// what it writes is private to their household, and a meal they cannot read is "no such meal".
//
// Arguments: do (cook, skip, unskip), token, entry (a MealPlanEntry's id), and for skip, instead (a
// recipe from the book, which is planned in the meal's place, or words for anything else). Returns
// {action, problem, process, created, notes}, as the pages record a booking.

return bookForCaller(WEEK_ACTIONS, $.methodParameters || {});
