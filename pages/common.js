// Shared by every page, after the engine code in pages/lib/: tools/install_pages.py puts them before
// each page's own script, inside one ${{ ... }} block run by Structr (JavaScript, as the signed-in
// user, so it sees what they may see). What is here is the pages' alone: escaping, the navigation,
// the week a page is about, and running a booking from a page's address. The pages work out what
// they show with pages/lib/, as the Python tools do; tools/check_pages.py compares the two.

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);

const PAGES = [["week", "Week"], ["shopping", "Shopping"], ["recipes", "Recipes"], ["nutrition", "Nutrition"], ["pantry", "Pantry"]];
function nav(here) {
  return "<nav>" + PAGES.map(([name, label]) => name === here ? "<b>" + label + "</b>"
    : "<a href=\"/structr/html/" + name + "\">" + label + "</a>").join(" · ") + "</nav>";
}

// The MealPlan a week page is about: the one named in its address (/structr/html/week/<id or name>),
// else the latest with entries
function chosenWeek() {
  if ($.current && $.current.type === "MealPlan") return $.current;
  const weeks = weeksWithEntries();
  return weeks.length ? weeks[0] : null;
}

function weekPicker(page, current) {
  const weeks = weeksWithEntries();
  if (weeks.length < 2) return "";
  return "<p class=\"weeks\">Other weeks: " + weeks.filter((w) => !current || w.id !== current.id)
    .map((w) => "<a href=\"/structr/html/" + page + "/" + w.id + "\">" + esc(w.name) + "</a>").join(" · ") + "</p>";
}

// A problem said on a page, as a sentence: "Problem: " and the words, a full stop added where they have none
function problemText(words) {
  const text = String(words);
  return "<p class=\"problem\">Problem: " + esc(text) + (/[.!?]$/.test(text) ? "" : ".") + "</p>";
}

// Run a booking from the page's address (?do=...); a message saying what it did. A Person signed in who is
// in one household books as themselves, for it (Path S stage 5, docs/methods.md): what it writes is private
// to the household, and it acts on the household's own data only, as the methods do. On an instance with no
// household yet (the development stack, whose checks book as a Person in none) a booking runs as the
// superuser, as every booking did before. On one with households, anyone in none (or in several) is
// refused: running as the superuser would let them book on a household's stock they cannot even see.
// A booking in SHARED_BOOKINGS adds shared knowledge (a product and its barcode: every user has it at once,
// the owner's rule of 2026-11-23), which no one may write as themselves, so it runs as the superuser for
// anyone signed in.
// BOOKED then holds the booking's action and its problem (null once it was booked)
let BOOKED = null;
const SHARED_BOOKINGS = {product: true};
function runBooking(actions) {
  const action = $.request.do;
  if (!action) return "";
  if (!actions[action]) return problemText("\"" + action + "\" isn't something this page can do");
  const token = String($.request.token || "");
  if (!/^[0-9a-f]{4,16}$/.test(token)) return problemText("this form is out of date. Reload the page and try again");
  const households = $.me && $.me.type === "Person" ? ($.me.groups || []).filter((g) => g.type === "Household") : [];
  const shared = !!SHARED_BOOKINGS[action];
  const household = !shared && households.length === 1 ? households[0] : null;
  let anyHousehold = false;
  if (!shared && !household) {
    const look = () => { anyHousehold = $.find("Household").length > 0; };
    if (typeof $.doPrivileged === "function") $.doPrivileged(look); else look();
  }
  if (anyHousehold) {
    BOOKED = {action: action, problem: "not in a household"};
    return problemText(householdProblem(households.length))
      + "<script type=\"application/json\" id=\"booking-data\">" + JSON.stringify({action: action, privileged: false,
        household: null, problem: BOOKED.problem, process: null, created: [], notes: []}) + "</script>";
  }
  let done = null;
  const run = () => { done = bookOnce(actions, action, $.request, token, household); };
  const privileged = !household && typeof $.doPrivileged === "function";
  if (privileged) $.doPrivileged(run); else run();
  const problem = done.problem, booking = done.booking;
  BOOKED = {action: action, problem: problem};
  // what was booked, for tools/check_bookings.py
  const record = "<script type=\"application/json\" id=\"booking-data\">" + JSON.stringify({
    action: action, privileged: privileged, household: household ? household.name : null, problem: problem, process: booking.process, created: booking.created,
    notes: booking.notes}).replace(/</g, "\\u003c") + "</script>";
  if (problem) return problemText(problem) + record;
  const said = booking.process ? (booking.created.length ? "Saved." : "This was saved already, so nothing changed.") : "";
  return "<p class=\"booked\">" + [said].concat(booking.notes.map(esc)).filter((x) => x).join(" ") + "</p>" + record
    + "<script>(function () { var keep = /[?&](sort=[^&]*)/.exec(location.search);"
    + " history.replaceState(null, '', location.pathname + (keep ? '?' + keep[1] : '')); })();</script>";
}
