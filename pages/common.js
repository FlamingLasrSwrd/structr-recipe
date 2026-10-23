// Shared by every page: tools/install_pages.py puts it before each page's own script, inside one
// ${{ ... }} block run by Structr (JavaScript, as the signed-in user, so it sees what they may see).
//
// The pages read the graph and work out what they show, as the Python tools do. Each function
// below names the Python one it follows; tools/check_pages.py compares what the pages show with
// what those functions give. Nothing here writes.

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

// defaults.resolve_default: the nearest Type with any applicable default of the kind wins; within it,
// the one with the most keys, all among `keyIds`; two tied are ambiguous (an error, as in Python)
function resolveDefault(type, kindName, keyIds) {
  for (const level of ancestorsOrSelf(type)) {
    const applicable = (level.defaultSpecifications || []).filter((d) => d.hasKind && d.hasKind.name === kindName)
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

const PAGES = [["week", "Week"], ["recipes", "Recipes"], ["nutrition", "Nutrition"], ["pantry", "Pantry"]];
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
