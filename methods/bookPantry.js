// bookPantry: one pantry booking for the caller's household, as the pantry page's forms make them
// (PANTRY_ACTIONS; mealplanner/pantry.py), but as the caller rather than the superuser: what it
// writes is private to their household, and it sees only what they may read, so a portion of another
// household is "no such portion". One at a time, committed before it answers, like the pages'.
//
// Arguments: do (buy, use, count, open, move, discard), token (4 to 16 hex digits, one per booking:
// the same token again writes nothing new), and the booking's fields: food, amount, unit, storage,
// keeps, portion. Returns {action, problem, process, created, notes}, as the pages record a booking.

return bookForCaller(PANTRY_ACTIONS, $.methodParameters || {});
