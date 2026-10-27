// pages/lib: the engine code the pages and the Structr methods share (tools/install_pages.py and
// tools/install_methods.py put every file here, in name order, before a page's or a method's own
// script). Each function names the Python one it follows; tools/check_pages.py compares the two.
//
// Units, defaults resolved along a Type's hierarchy, days and how numbers are written.

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
