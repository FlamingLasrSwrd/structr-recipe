// bookPantry: one pantry booking for the caller's household, as the pantry page's forms make them
// (PANTRY_ACTIONS; mealplanner/pantry.py), but as the caller rather than the superuser: what it
// writes is private to their household, and it sees only what they may read, so a portion of another
// household is "no such portion". One at a time, committed before it answers, like the pages'.
//
// Arguments: do (buy, use, count, open, move, discard), token (4 to 16 hex digits, one per booking:
// the same token again writes nothing new), and the booking's fields: food, amount, unit, storage,
// keeps, portion. Returns {action, problem, process, created, notes}, as the pages record a booking.

const asked = $.methodParameters || {};
const action = String(asked.do || "");
const token = String(asked.token || "");
const households = (($.me && $.me.groups) || []).filter((g) => g.type === "Household");
let answer;
if (households.length !== 1) {
  answer = {action: action, problem: "a booking is for one household, and you are in " + households.length};
} else if (!PANTRY_ACTIONS[action]) {
  answer = {action: action, problem: "no such booking: " + action};
} else if (!/^[0-9a-f]{4,16}$/.test(token)) {
  answer = {action: action, problem: "a booking needs a token of 4 to 16 hex digits"};
} else {
  const done = bookOnce(PANTRY_ACTIONS, action, asked, token, households[0]);
  answer = {action: action, problem: done.problem, process: done.booking.process, created: done.booking.created,
            notes: done.booking.notes};
}
return answer;
