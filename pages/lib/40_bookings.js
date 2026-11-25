// Bookings (mealplanner/pantry.py): how every booking writes: for the caller's household, as the caller (the
// methods', and a page's by a household's member), or as the superuser (a page's by anyone else).

// A form carries a token made when the page was drawn, and every node a booking writes is found by
// name before it is created, so sending a form twice writes nothing new (CLAUDE.md hard rule 5).
// Every write states its visibility (rule 4). A booking made for a household (the methods, and a page's by a
// Person in one household: Path S, docs/architecture-decision.md §7a, stage 5) runs as the caller and writes
// nodes private to that household: seen by no one else, granted to its Group, so every member reads and
// changes them. It never makes shared vocabulary. Anyone else's page booking runs as the superuser
// ($.doPrivileged), as every booking did before, and writes what every signed-in user sees.
//
// One booking at a time, each committed before the page answers (REVIEW.md round 3 #9; measured on
// Structr 6.0.0, docs/structr-cheatsheet.md). Two presses at once each found no node of a name and each
// made one, and a page answered "booked" before its write committed, even when the commit then failed.
// So a booking runs in a transaction of its own, which first writes to one lock node: Neo4j holds that
// write until the commit, so a second booking waits there and then finds what the first made. The lock
// comes before any read, because a read repeated within a transaction answers as it did the first time.
// tools/install_pages.py makes the lock node, outside the model (no Structr type; nothing else reads it):
// made by the first booking instead, two bookings in that first moment each made one.
// A method's booking for a household takes that household's turn instead: it first writes
// Household.bookingTurn, an ordinary Structr write that Neo4j holds the same way, so households never
// wait on each other. Not the Cypher lock, because a Cypher write made Structr answer 404 to methods
// called at the same moment (docs/structr-cheatsheet.md §3a); a page's booking by an account in no household
// keeps it.
const LOCK = "MATCH (l:MealPlannerBookingLock) WITH l ORDER BY elementId(l) LIMIT 1 SET l.at = timestamp() RETURN count(l) AS n";
const SEEN = {visibleToAuthenticatedUsers: true, visibleToPublicUsers: false};
const PRIVATE = {visibleToAuthenticatedUsers: false, visibleToPublicUsers: false};
const stamp = (d) => d.toISOString().replace(/\.\d{3}Z$/, "+0000");
// pantry.signed_in_person: who is signed in, if they are a Person (data-model.md K1), taken before a page's
// booking may run as the superuser ($.doPrivileged), where $.me may be someone else. Each booking's Process
// names them (wasAssociatedWith), a stock take's, an opening's and a move's too (2026-11-23).
const BOOKED_BY = $.me && $.me.type === "Person" ? $.me.id : null;
const newToken = () => Math.random().toString(16).slice(2, 10);

class BookingError extends Error {}

// What a booking by someone in no household, or in several, is told (a page's and a method's alike)
const householdProblem = (n) => n ? "your account is in more than one household, so whose this is can't be told. "
  + "Ask whoever runs the planner to fix your account"
  : "your account isn't in a household yet, so there is nothing of yours to change. Ask whoever runs the planner to add you";

// typetree.dt: the one DomainType with this name
function typeNamed(name) {
  const found = $.find("DomainType", {name: name});
  if (!found.length) throw new BookingError("\"" + name + "\" isn't known here. Check the spelling, or pick it from the list");
  if (found.length > 1) throw new BookingError("more than one thing is called \"" + name + "\", so which one is meant can't be told");
  return found[0];
}

// pantry._Writer.ensure: find by name, else create; `booking.created` lists what was created. A
// household's booking finds among its own nodes only (private to it): a node of the same name that
// every signed-in user sees is no household's, and is neither reused nor changed
function ensureNode(booking, type, name, props) {
  if (/[,;]/.test(name)) throw new BookingError("a name can't contain a comma or a semicolon. Take them out of \"" + name + "\" and try again");
  const found = $.find(type, {name: name})
    .filter((n) => n.type === type && (!booking.household || n.visibleToAuthenticatedUsers === false));
  if (found.length > 1) throw new BookingError("two " + type + " records are named \"" + name + "\", so nothing can be saved until one is removed");
  if (found.length) return found[0];
  const fields = {name: name};
  for (const key of Object.keys(props)) if (props[key] != null) fields[key] = props[key];
  booking.created.push(name);
  const node = $.create(type, Object.assign(fields, booking.household ? PRIVATE : SEEN));
  if (booking.household) $.grant(booking.household, node, "read, write, delete");
  return node;
}

// pantry._operation: a Process kind in the Pantry Operation hierarchy, made on first use; a household's
// booking finds it, since it is shared vocabulary
function operationKind(booking, kind) {
  if (booking.household) return typeNamed(kind);
  const hierarchy = $.find("TypeHierarchy", {name: "Pantry Operation"})[0] || ensureNode(booking, "TypeHierarchy", "Pantry Operation", {});
  return ensureNode(booking, "DomainType", kind, {hierarchy: hierarchy, isLookupBearing: false});
}

// pantry._process
function bookProcess(booking, kind, name, when, extra) {
  const region = ensureNode(booking, "TemporalRegion", name + " time", {hasBeginning: stamp(when)});
  booking.process = name;
  return ensureNode(booking, "Process", name, Object.assign({hasKind: kind ? operationKind(booking, kind) : null,
                                                             occupiesTemporalRegion: region,
                                                             wasAssociatedWith: bookedBy()}, extra || {}));
}

// The signed-in Person, loaded again in the booking's own transaction, as a list for wasAssociatedWith; null
// for anyone else (the tools' account, the superuser)
function bookedBy() {
  if (!BOOKED_BY) return null;
  const found = $.find("Person", {id: BOOKED_BY});
  const person = Array.isArray(found) ? found[0] : found;
  return person ? [person] : null;
}

// pantry._draw: an input Allocation of `grams` from a portion, its amount an observed Measurement; `via` the
// SubstitutionRule a cook's draw followed (substitutes.py), if any
function bookDraw(booking, process, portion, grams, when, label, spec, via) {
  const name = process.name + " -- " + label;
  const amount = ensureNode(booking, "Measurement", name + " amount", {value: Math.round(grams * 1e6) / 1e6, unit: "g",
                                                                      status: "observed", hasTime: stamp(when)});
  ensureNode(booking, "Allocation", name, {isAbout: portion, hasParticipationRole: "input", hasActualQuantity: amount,
                                           process: process, fulfills: spec || null, viaSubstitution: via || null});
}

// One booking, in a transaction of its own, after the lock: its problem (or null) and what it wrote.
// `household` is null for the pages' bookings, a Household for the methods'
function bookOnce(actions, action, request, token, household) {
  const booking = {process: null, created: [], notes: [], household: household};
  let problem = null;                   // said inside: an error does not cross a transaction as itself
  const work = () => {
    try {
      if (household) {
        $.doPrivileged(() => {                // loaded again here: an object keeps the rights it was loaded with
          const turn = $.find("Household", {id: household.id});
          (Array.isArray(turn) ? turn[0] : turn).bookingTurn = token + " " + Date.now() + " " + Math.random();
        });
      } else {
        const lock = $.cypher(LOCK);
        if (!lock.length || !lock[0].n) throw new BookingError("the planner isn't fully installed, so nothing was saved. Run tools/install_pages.py again");
      }
      actions[action](booking, request, token);
    } catch (e) {
      problem = e instanceof BookingError ? e.message : "something went wrong, so nothing was saved (" + (e.message || e) + ")";
      throw e;                          // so that nothing of it is kept
    }
  };
  const failed = (e) => {               // thrown above, or the commit refused (a validator, a unique name)
    if (!problem) problem = "the database refused the change, so nothing was saved (" + (e && e.message || e) + ")";
    booking.created = [];
    booking.notes = [];
  };
  $.doInNewTransaction(work, failed);
  return {problem: problem, booking: booking};
}

// A booking a method makes for its caller (bookPantry, bookWeek, bookRequest): for their one household,
// as they are, so it writes what is private to that household and sees only what they may read.
// The answer is what the pages record of a booking.
function bookForCaller(actions, asked) {
  const action = String(asked.do || ""), token = String(asked.token || "");
  const households = (($.me && $.me.groups) || []).filter((g) => g.type === "Household");
  if (households.length !== 1) return {action: action, problem: householdProblem(households.length)};
  if (!actions[action]) return {action: action, problem: "\"" + action + "\" isn't something this can do"};
  if (!/^[0-9a-f]{4,16}$/.test(token)) return {action: action, problem: "the request needs a token of 4 to 16 hex digits"};
  const done = bookOnce(actions, action, asked, token, households[0]);
  return {action: action, problem: done.problem, process: done.booking.process, created: done.booking.created,
          notes: done.booking.notes};
}
