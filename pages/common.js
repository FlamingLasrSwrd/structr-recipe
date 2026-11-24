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

// Whether a booking came from one of this instance's own pages (docs/pages.md, "Bookings from another
// site"). A booking is a link (?do=...), and the browser sends the session cookie with a link followed
// from another site (SameSite=Lax), so without this a page anywhere on the internet, opened while signed
// in, could book on the household's pantry. The browser says where a request came from: Sec-Fetch-Site
// (every current browser), else the Referer, whose host must be this one; a request that says neither is
// refused, failing closed. A request signed in by its own headers (the tools' X-User, or a session token
// sent as X-StructrSessionToken) carries no cookie a browser added for it, so it is not checked: another
// site cannot make a browser send those headers to this one, and could not fill them in if it could.
function fromOwnPage() {
  const header = (name) => {
    try { const v = $.getRequestHeader(name); return v == null ? "" : String(v); } catch (e) { return ""; }
  };
  if (header("X-User") || header("X-StructrSessionToken")) return true;
  const site = header("Sec-Fetch-Site").toLowerCase();
  if (site) return site === "same-origin";
  const from = /^https?:\/\/([^\/?#]+)/i.exec(header("Referer")), host = header("Host").toLowerCase();
  return !!(from && host && from[1].toLowerCase() === host);
}

function runBooking(actions) {
  const action = $.request.do;
  if (!action) return "";
  if (!actions[action]) return "<p class=\"problem\">Problem: no such booking: " + esc(action) + "</p>";
  const token = String($.request.token || "");
  if (!/^[0-9a-f]{4,16}$/.test(token)) return "<p class=\"problem\">Problem: the form had no token; reload the page and try again.</p>";
  if (!fromOwnPage()) {
    BOOKED = {action: action, problem: "not from this site"};
    return "<p class=\"problem\">Problem: this change did not come from one of the planner's own pages (a link from "
      + "another site or app, or a bookmark), so it was not saved. If you meant it, make it again on this page.</p>"
      + "<script type=\"application/json\" id=\"booking-data\">" + JSON.stringify({action: action, privileged: false,
        household: null, problem: BOOKED.problem, process: null, created: [], notes: []}) + "</script>";
  }
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
    return "<p class=\"problem\">Problem: " + (households.length ? "you are in more than one household, so whose this "
      + "booking is cannot be told" : "you are in no household, so there is no stock of yours to book on") + ".</p>"
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
  if (problem) return "<p class=\"problem\">Problem: " + esc(problem) + "</p>" + record;
  const said = booking.process ? (booking.created.length ? esc(booking.process) + ": booked."
                                                          : esc(booking.process) + ": booked before, so nothing new was written.") : "";
  return "<p class=\"booked\">" + [said].concat(booking.notes.map(esc)).filter((x) => x).join(" ") + "</p>" + record
    + "<script>history.replaceState(null, '', location.pathname);</script>";
}
