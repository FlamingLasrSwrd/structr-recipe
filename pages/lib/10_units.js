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

// weights.TIDY_STEPS, STEP_SHARE, SMALLEST_WEIGHED_G: amounts shown as weights (docs/recipe-format.md)
const TIDY_STEPS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
const STEP_SHARE = 0.1, SMALLEST_WEIGHED_G = 10;

// weights.tidy_step: the tidy step nearest x on a ratio scale
function tidyStep(x) {
  for (let k = 0; k + 1 < TIDY_STEPS.length; k++) if (x * x <= TIDY_STEPS[k] * TIDY_STEPS[k + 1]) return TIDY_STEPS[k];
  return TIDY_STEPS[TIDY_STEPS.length - 1];
}

// weights.rounding_step: a tenth of an item, else of a usual serving, made tidy; null with neither
function roundingStep(food) {
  const base = food ? (food.each || food.serving) : null;
  return base ? tidyStep(base * STEP_SHARE) : null;
}

// weights.to_grams over facts already read
function gramsOf(amount, unit, food) {
  const entry = UNIT_TABLE[String(unit || "").trim().toLowerCase()];
  if (amount == null || !entry) return null;
  if (entry[0] === "mass") return amount * entry[1];
  if (entry[0] === "volume" && food && food.density) return amount * entry[1] * food.density;
  return null;
}

// weights.shown_amount: [amount, unit] as a person who prefers weights is shown it
function shownAmount(amount, unit, food) {
  const entry = UNIT_TABLE[String(unit || "").trim().toLowerCase()];
  if (amount == null || !entry || entry[0] === "count") return [amount, unit];
  const grams = gramsOf(amount, unit, food);
  if (grams == null || (entry[0] === "volume" && grams < SMALLEST_WEIGHED_G)) return [amount, unit];
  const step = roundingStep(food) || 1;
  const rounded = Math.floor(Math.floor(grams / step + 0.5) * step * 1e6 + 0.5) / 1e6;   // 71 * 0.1 is 7.1000000000000005
  return rounded <= 0 ? [amount, unit] : [rounded, "g"];
}

// weights.food_weights: a food Type's density, weight per item and usual serving (grams), resolved along
// its hierarchy; each null where it has none
function foodWeights(type) {
  const value = (kind, unit) => {
    const d = type ? resolveDefault(type, kind, []) : null;
    const q = d && d.hasValue;
    return q && q.value != null && (!unit || q.unit === unit) ? q : null;
  };
  const density = value("Density", "g_per_mL"), each = value("MassPerUnit", "g_per_each"), serving = value("ServingSize", null);
  const d = density ? density.value : null;
  return {density: d, each: each ? each.value : null,
          serving: serving ? gramsOf(serving.value, serving.unit, {density: d}) : null};
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
