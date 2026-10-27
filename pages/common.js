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

// Run a booking from the page's address (?do=...), as the superuser; a message saying what it did
function runBooking(actions) {
  const action = $.request.do;
  if (!action) return "";
  if (!actions[action]) return "<p class=\"problem\">Problem: no such booking: " + esc(action) + "</p>";
  const token = String($.request.token || "");
  if (!/^[0-9a-f]{4,16}$/.test(token)) return "<p class=\"problem\">Problem: the form had no token; reload the page and try again.</p>";
  let done = null;
  const run = () => { done = bookOnce(actions, action, $.request, token, null); };
  const privileged = typeof $.doPrivileged === "function";
  if (privileged) $.doPrivileged(run); else run();
  const problem = done.problem, booking = done.booking;
  // what was booked, for tools/check_bookings.py
  const record = "<script type=\"application/json\" id=\"booking-data\">" + JSON.stringify({
    action: action, privileged: privileged, problem: problem, process: booking.process, created: booking.created,
    notes: booking.notes}).replace(/</g, "\\u003c") + "</script>";
  if (problem) return "<p class=\"problem\">Problem: " + esc(problem) + "</p>" + record;
  const said = booking.process ? (booking.created.length ? esc(booking.process) + ": booked."
                                                          : esc(booking.process) + ": booked before, so nothing new was written.") : "";
  return "<p class=\"booked\">" + [said].concat(booking.notes.map(esc)).filter((x) => x).join(" ") + "</p>" + record
    + "<script>history.replaceState(null, '', location.pathname);</script>";
}
