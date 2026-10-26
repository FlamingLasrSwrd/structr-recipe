// Shared by every page: tools/install_pages.py puts it before each page's own script, inside one
// ${{ ... }} block run by Structr (JavaScript, as the signed-in user, so it sees what they may see).
//
// The pages read the graph and work out what they show, as the Python tools do. Each function
// below names the Python one it follows; tools/check_pages.py compares what the pages show with
// what those functions give. Only the bookings at the end write: the pantry and week pages' forms
// (mealplanner/pantry.py, docs/pantry.md).

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);

// nutrition_scope.NUTRIENT_UNITS: unit -> [dimension, factor to its base unit]
const NUTRIENT_UNITS = {g: ["mass", 1], mg: ["mass", 1e-3], ug: ["mass", 1e-6], "µg": ["mass", 1e-6],
                        kcal: ["energy", 1], kj: ["energy", 1 / 4.184], iu: ["iu", 1]};

// nutrition_scope.convert_nutrient: null across dimensions or for an unknown unit
function convertNutrient(amount, from, to) {
  const a = NUTRIENT_UNITS[String(from || "").trim().toLowerCase()];
  const b = NUTRIENT_UNITS[String(to || "").trim().toLowerCase()];
  if (!a || !b || a[0] !== b[0]) return null;
  return a[1] === b[1] ? amount : amount * a[1] / b[1];
}

// unit_conversion.UNIT_TABLE
const UNIT_TABLE = {g: ["mass", 1], gram: ["mass", 1], grams: ["mass", 1], kg: ["mass", 1000], mg: ["mass", 0.001],
                    oz: ["mass", 28.3495], lb: ["mass", 453.592], ml: ["volume", 1], l: ["volume", 1000],
                    cup: ["volume", 236.588], tbsp: ["volume", 14.7868], tsp: ["volume", 4.92892],
                    fl_oz: ["volume", 29.5735], dash: ["volume", 4.92892 / 8], pinch: ["volume", 4.92892 / 16],
                    each: ["count", 1], whole: ["count", 1], count: ["count", 1]};

// typetree.ancestors_or_self
function ancestorsOrSelf(type) {
  const chain = [], seen = {};
  for (let t = type; t && !seen[t.id]; t = t.parent) {
    seen[t.id] = true;
    chain.push(t);
  }
  return chain;
}

// A Type's defaults by kind name, read once per page: a retention class holds a default for every
// nutrient and method (J30), and reading each one's kind again for every lookup that walks past it
// cost the shopping page about a second
const defaultsByType = {};
function defaultsOf(level, kindName) {
  if (!defaultsByType[level.id]) {
    const byKind = {};
    for (const d of level.defaultSpecifications || []) {
      if (d.hasKind) (byKind[d.hasKind.name] = byKind[d.hasKind.name] || []).push(d);
    }
    defaultsByType[level.id] = byKind;
  }
  return defaultsByType[level.id][kindName] || [];
}

// defaults.resolve_default: the nearest Type with any applicable default of the kind wins; within it,
// the one with the most keys, all among `keyIds`; two tied are ambiguous (an error, as in Python)
function resolveDefault(type, kindName, keyIds) {
  for (const level of ancestorsOrSelf(type)) {
    const applicable = defaultsOf(level, kindName)
      .filter((d) => (d.keyedBy || []).every((k) => keyIds.indexOf(k.id) >= 0));
    if (!applicable.length) continue;
    const most = Math.max(...applicable.map((d) => (d.keyedBy || []).length));
    const best = applicable.filter((d) => (d.keyedBy || []).length === most);
    if (best.length > 1) throw new Error("ambiguous " + kindName + " defaults on " + level.name);
    return best[0];
  }
  return null;
}

// unit_conversion.convert_to_grams: null when unconvertible (no density or weight per item resolves)
function toGrams(type, value, unit) {
  const entry = UNIT_TABLE[String(unit || "").trim().toLowerCase()];
  if (value == null || !entry) return null;
  if (entry[0] === "mass") return value * entry[1];
  if (!type) return null;
  const kind = entry[0] === "volume" ? ["Density", "g_per_mL"] : ["MassPerUnit", "g_per_each"];
  const d = resolveDefault(type, kind[0], []);
  const q = d && d.hasValue;
  if (!q || q.value == null || q.unit !== kind[1]) return null;
  return value * entry[1] * q.value;
}

// nutrition_scope.day_zone: the zone whose midnight a dayBoundaryRule names, or null
function zoneOf(rule) {
  if (rule === "midnight") return "UTC";
  if (typeof rule === "string" && rule.indexOf("midnight ") === 0) return rule.substring(9);
  return null;
}

const dayKey = (d, zone) => new Intl.DateTimeFormat("en-CA", {timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit"}).format(d);
const dayLabel = (d, zone) => new Intl.DateTimeFormat("en-US", {timeZone: zone, weekday: "short", month: "short", day: "numeric"}).format(d);
const clock = (d, zone) => new Intl.DateTimeFormat("en-GB", {timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: false}).format(d);
const whenLabel = (d, zone) => new Intl.DateTimeFormat("en-US", {timeZone: zone, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false}).format(d);

const number = (x, places) => x == null ? "?" : Number(x).toLocaleString("en-US", {maximumFractionDigits: places == null ? 1 : places});

// nutrition_scope.entry_start
function startOf(entry) {
  const region = entry.isAbout;
  return region && region.hasBeginning ? new Date(region.hasBeginning) : null;
}

// nutrition_scope.active_entries, in time order (an entry with no start last)
function activeEntries(mealPlan) {
  return (mealPlan.hasEntry || []).filter((e) => !e.isSkipped)
    .sort((a, b) => (startOf(a) || new Date(8.64e15)) - (startOf(b) || new Date(8.64e15)));
}

// nutrition_scope._source_plan: an entry's own recipe, or for leftovers the source's, following the chain
function planOf(entry) {
  const seen = {};
  let current = entry;
  for (let hop = 0; hop <= 5 && current; hop++) {
    if (current.references) return current.references;
    const source = current.consumesLeftoverFrom;
    if (!source || seen[source.id]) return null;
    seen[source.id] = true;
    current = source;
  }
  return null;
}

// nutrition_scope.entry_servings_eaten: [servings, whether the default was assumed]
function servingsEaten(holder) {
  const q = holder.hasPlannedConsumption;
  if (q && q.value != null && q.value >= 0 && q.unit === "servings") return [q.value, false];
  return [1.0, true];
}

// nutrition_scope.eaten_by_no_one: a dish made at a prep session, eaten later as leftovers
const eatenByNoOne = (entry) => !(entry.hasShare || []).length && !servingsEaten(entry)[1] && servingsEaten(entry)[0] <= 0;

// nutrition_scope.entry_person_servings
function personServings(entry, person) {
  const shares = entry.hasShare || [];
  if (!shares.length) return servingsEaten(entry);
  let total = 0, assumed = false;
  for (const share of shares) {
    if (share.eatenBy && share.eatenBy.id === person.id) {
      const [servings, was] = servingsEaten(share);
      total += servings;
      assumed = assumed || was;
    }
  }
  return [total, assumed];
}

// nutrition_scope.stored_figure: a recipe's stored nutrition per serving (J28), in `unit`.
// {amount, trusted, estimated, reason}; amount null when unknown. null when nothing is stored, where
// Python would work the figure out from the ingredients: tools/calculate_recipe_nutrition.py stores it.
const USABLE = ["sourced", "estimated", "calculated"];
const storedByPlan = {};               // a recipe's stored figures by nutrient id, read once per page
function storedOf(plan) {
  if (!storedByPlan[plan.id]) {
    const byNutrient = {};
    for (const p of plan.servingProfiles || []) {
      if (p.basis !== "per_serving" || !p.forNutrient) continue;
      (byNutrient[p.forNutrient.id] = byNutrient[p.forNutrient.id] || []).push(p);
    }
    storedByPlan[plan.id] = byNutrient;
  }
  return storedByPlan[plan.id];
}
function servingFigure(plan, nutrientId, unit) {
  const rows = storedOf(plan)[nutrientId] || [];
  if (rows.length !== 1) return null;
  const p = rows[0];
  if (p.amount == null) return {amount: null, trusted: false, estimated: false, reason: p.source || "unknown"};
  const amount = convertNutrient(p.amount, p.unit, unit);
  if (amount == null) return {amount: null, trusted: false, estimated: false, reason: "stored in " + p.unit + ", not comparable with " + unit};
  return {amount: amount, trusted: USABLE.indexOf(p.provenance) >= 0, estimated: p.provenance === "estimated",
          reason: p.provenance === "calculated" ? null : p.source};
}

// The day boundary of a MealPlan's daily targets, for laying its entries out by day
function weekZone(mealPlan) {
  for (const c of mealPlan.hasConstraint || []) {
    const zone = c.type === "NutritionTarget" ? zoneOf(c.dayBoundaryRule) : null;
    if (zone) return zone;
  }
  return "UTC";
}

const PAGES = [["week", "Week"], ["shopping", "Shopping"], ["recipes", "Recipes"], ["nutrition", "Nutrition"], ["pantry", "Pantry"]];
function nav(here) {
  return "<nav>" + PAGES.map(([name, label]) => name === here ? "<b>" + label + "</b>"
    : "<a href=\"/structr/html/" + name + "\">" + label + "</a>").join(" · ") + "</nav>";
}

// The MealPlans with entries, the latest first by the start of their region
function weeksWithEntries() {
  return $.find("MealPlan").filter((m) => (m.hasEntry || []).length)
    .sort((a, b) => new Date((b.isAbout && b.isAbout.hasBeginning) || 0) - new Date((a.isAbout && a.isAbout.hasBeginning) || 0));
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

// -- stock on hand (inventory.py), shared by the pantry and shopping pages ------------------------
const NOW = new Date();

// inventory.mass_quality
const massQuality = (portion) => (portion.bearerOf || []).find((q) => q.type === "Quality" && q.hasKind && q.hasKind.name === "Mass") || null;

// inventory._baselines (a portion's weighings): observed or imputed Measurements with a time, oldest first
const weighingsOf = (quality) => (quality.measurements || []).filter((m) => (m.status === "observed" || m.status === "imputed") && m.hasTime)
  .map((m) => [new Date(m.hasTime), m]).sort((a, b) => a[0] - b[0]);

// inventory._draws: [time, grams or null, problem]
function draws(portion, type) {
  const out = [];
  for (const a of portion.allocationsAbout || []) {
    if (a.hasParticipationRole !== "input" || !a.process) continue;
    const region = a.process.occupiesTemporalRegion;
    if (!region || !region.hasBeginning) return null;               // Python raises: a use with no time
    const q = a.hasActualQuantity;
    const grams = q ? toGrams(type, q.value, q.unit) : null;
    out.push([new Date(region.hasBeginning), grams, grams == null ? "a use with no amount in grams" : null]);
  }
  return out;
}

// inventory._level_at, at now: [grams, the weighing used] or null, or a string saying why it cannot be told
function onHand(portion) {
  const quality = massQuality(portion);
  if (!quality) return null;
  const type = portion.instanceOf;
  const known = weighingsOf(quality).filter(([t]) => t <= NOW);
  if (!known.length) return null;
  const [since, weighing] = known[known.length - 1];
  let level = toGrams(type, weighing.value, weighing.unit);
  if (level == null) return "weighed in " + weighing.unit + ", which does not convert to grams";
  const used = draws(portion, type);
  if (used == null) return "a use with no time";
  for (const [at, grams, problem] of used) {
    if (at < since || at > NOW) continue;
    if (problem) return problem;
    level -= grams;
  }
  return [level, weighing, since];
}

// inventory.assumed_storage: a portion in no container is kept where its food keeps longest unopened,
// of the fridge and the pantry, the fridge on a tie or when it has neither (J31)
function assumedStorage(portion) {
  const own = {};
  for (const d of portion.instanceOf ? defaultsOf(portion.instanceOf, "ShelfLife") : []) {
    const names = (d.keyedBy || []).map((k) => k.name);
    if (names.indexOf("Opened") >= 0 || !d.hasValue || d.hasValue.value == null) continue;
    for (const storage of names) own[storage] = d.hasValue.value;
  }
  const days = (storage) => (storage in own ? own[storage] : -1);
  return days("Pantry") > days("Fridge") ? "Pantry" : "Fridge";
}

// inventory.portion_shelf_life: its food's shelf life (FoodKeeper's), else its perishability class's
function portionShelfLife(portion, keys) {
  const valid = (d) => d && d.hasValue && d.hasValue.unit === "days" && d.hasValue.value != null ? d.hasValue.value : null;
  const own = portion.instanceOf ? valid(resolveDefault(portion.instanceOf, "ShelfLife", keys)) : null;
  if (own != null) return own;
  return portion.hasPerishabilityType ? valid(resolveDefault(portion.hasPerishabilityType, "ShelfLife", keys)) : null;
}

// inventory.instance_expiration: days until it expires (negative: expired), or null if it cannot be told
const typeId = (name) => { const t = $.find("DomainType", {name: name})[0]; return t ? t.id : null; };
function daysUntilExpiry(portion) {
  const quality = massQuality(portion);
  if (!quality || (!portion.instanceOf && !portion.hasPerishabilityType)) return [null, "no food or perishability"];
  const weighed = weighingsOf(quality).filter(([t]) => t <= NOW);
  if (!weighed.length) return [null, "not weighed yet"];
  let started = weighed[0][0];
  const origin = portion.beginsToExistDuring;
  if (origin) {
    const region = origin.occupiesTemporalRegion;
    if (!region || !region.hasBeginning) return [null, "bought by a process with no date"];
    started = new Date(region.hasBeginning);
  }
  const box = portion.locatedIn;
  const opened = (box && box.hasOpenedStatus && box.hasOpenedStatus.name) || "Sealed";
  const stated = box && box.hasStorageCondition && box.hasStorageCondition.name;
  const kept = stated || assumedStorage(portion);
  const days = portionShelfLife(portion, [typeId(kept), typeId(opened)]);
  const where = kept + ", " + opened + (stated ? "" : ", assumed");
  if (days == null) return [null, "no shelf life " + (kept === "Pantry" ? "in the pantry" : kept === "Fridge" ? "in the fridge" : "in the freezer") + " (" + where + ")"];
  return [(started.getTime() + days * 86400e3 - NOW.getTime()) / 86400e3, where];
}

// subtypes_of: a Type and every Type below it
function subtypesOf(type) {
  const out = {}, todo = [type];
  while (todo.length) {
    const t = todo.pop();
    if (out[t.id]) continue;
    out[t.id] = true;
    for (const child of t.children || []) todo.push(child);
  }
  return out;
}

// -- bookings (mealplanner/pantry.py): what the pantry and week pages' forms write ----------------
// A form carries a token made when the page was drawn, and every node a booking writes is found by
// name before it is created, so sending a form twice writes nothing new (CLAUDE.md hard rule 5).
// Writes run as the superuser ($.doPrivileged), as the tools' do, and state their visibility (rule 4).
//
// One booking at a time, each committed before the page answers (REVIEW.md round 3 #1; measured on
// Structr 6.0.0, docs/structr-cheatsheet.md). Two presses at once each found no node of a name and each
// made one, and a page answered "booked" before its write committed, even when the commit then failed.
// So a booking runs in a transaction of its own, which first writes to one lock node: Neo4j holds that
// write until the commit, so a second booking waits there and then finds what the first made. The lock
// comes before any read, because a read repeated within a transaction answers as it did the first time.
// tools/install_pages.py makes the lock node, outside the model (no Structr type; nothing else reads it):
// made by the first booking instead, two bookings in that first moment each made one.
const LOCK = "MATCH (l:MealPlannerBookingLock) WITH l ORDER BY elementId(l) LIMIT 1 SET l.at = timestamp() RETURN count(l) AS n";
const SEEN = {visibleToAuthenticatedUsers: true, visibleToPublicUsers: false};
const stamp = (d) => d.toISOString().replace(/\.\d{3}Z$/, "+0000");
const newToken = () => Math.random().toString(16).slice(2, 10);

class BookingError extends Error {}

// typetree.dt: the one DomainType with this name
function typeNamed(name) {
  const found = $.find("DomainType", {name: name});
  if (found.length !== 1) throw new BookingError("expected exactly one DomainType named " + name + ", found " + found.length);
  return found[0];
}

// pantry._Writer.ensure: find by name, else create; `booking.created` lists what was created
function ensureNode(booking, type, name, props) {
  if (/[,;]/.test(name)) throw new BookingError(name + ": a name cannot hold a comma or a semicolon");
  const found = $.find(type, {name: name}).filter((n) => n.type === type);
  if (found.length > 1) throw new BookingError("two " + type + " nodes are named " + name);
  if (found.length) return found[0];
  const fields = {name: name};
  for (const key of Object.keys(props)) if (props[key] != null) fields[key] = props[key];
  booking.created.push(name);
  return $.create(type, Object.assign(fields, SEEN));
}

// pantry._operation: a Process kind in the Pantry Operation hierarchy, made on first use
function operationKind(booking, kind) {
  const hierarchy = $.find("TypeHierarchy", {name: "Pantry Operation"})[0] || ensureNode(booking, "TypeHierarchy", "Pantry Operation", {});
  return ensureNode(booking, "DomainType", kind, {hierarchy: hierarchy, isLookupBearing: false});
}

// pantry._process
function bookProcess(booking, kind, name, when, extra) {
  const region = ensureNode(booking, "TemporalRegion", name + " time", {hasBeginning: stamp(when)});
  booking.process = name;
  return ensureNode(booking, "Process", name, Object.assign({hasKind: kind ? operationKind(booking, kind) : null,
                                                             occupiesTemporalRegion: region}, extra || {}));
}

// pantry._draw: an input Allocation of `grams` from a portion, its amount an observed Measurement
function bookDraw(booking, process, portion, grams, when, label, spec) {
  const name = process.name + " -- " + label;
  const amount = ensureNode(booking, "Measurement", name + " amount", {value: Math.round(grams * 1e6) / 1e6, unit: "g",
                                                                      status: "observed", hasTime: stamp(when)});
  ensureNode(booking, "Allocation", name, {isAbout: portion, hasParticipationRole: "input", hasActualQuantity: amount,
                                           process: process, fulfills: spec || null});
}

// Run a booking from the page's address (?do=...), as the superuser; a message saying what it did
function runBooking(actions) {
  const action = $.request.do;
  if (!action) return "";
  if (!actions[action]) return "<p class=\"problem\">Problem: no such booking: " + esc(action) + "</p>";
  const token = String($.request.token || "");
  if (!/^[0-9a-f]{4,16}$/.test(token)) return "<p class=\"problem\">Problem: the form had no token; reload the page and try again.</p>";
  const booking = {process: null, created: [], notes: []};
  let problem = null;                   // said inside: an error does not cross a transaction as itself
  const work = () => {
    try {
      const lock = $.cypher(LOCK);
      if (!lock.length || !lock[0].n) throw new BookingError("the bookings' lock is missing: install the pages again (tools/install_pages.py)");
      actions[action](booking, $.request, token);
    } catch (e) {
      problem = e instanceof BookingError ? e.message : "the booking failed: " + (e.message || e);
      throw e;                          // so that nothing of it is kept
    }
  };
  const failed = (e) => {               // thrown above, or the commit refused (a validator, a unique name)
    if (!problem) problem = "the booking was not saved: " + (e && e.message || e);
    booking.created = [];
    booking.notes = [];
  };
  const run = () => { $.doInNewTransaction(work, failed); };
  const privileged = typeof $.doPrivileged === "function";
  if (privileged) $.doPrivileged(run); else run();
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


// -- recipes asked for a week (mealplanner/requests.py): the recipe page's "Cook in the week of ..." --
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

// requests._week: the MealPlan named for the week, or null
function weekNamed(start) {
  const found = $.find("MealPlan", {name: WEEK_PREFIX + start}).filter((m) => m.type === "MealPlan");
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
    const week = weekNamed(start) || ensureNode(booking, "MealPlan", WEEK_PREFIX + start, {});
    const current = (week.requestsRecipe || []).slice();
    if (current.some((x) => x.id === identity.id)) { booking.notes.push(identity.name + " was asked for in the week of " + weekWords(start) + " already."); return; }
    week.requestsRecipe = current.concat([identity]);
    booking.notes.push(identity.name + ": asked for in the week of " + weekWords(start) + ".");
  },
  // requests.withdraw
  withdraw: (booking, r) => {
    const start = String(r.week || ""), recipeId = String(r.recipe || "");
    const week = /^\d{4}-\d{2}-\d{2}$/.test(start) ? weekNamed(start) : null;
    const current = week ? (week.requestsRecipe || []).slice() : [];
    const found = current.find((x) => x.id === recipeId);
    if (!found) { booking.notes.push("It was not asked for that week."); return; }
    week.requestsRecipe = current.filter((x) => x.id !== recipeId);
    booking.notes.push(found.name + ": no longer asked for in the week of " + weekWords(start) + ".");
  },
};
