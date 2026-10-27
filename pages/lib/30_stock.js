// Stock on hand and when it expires (inventory.py).

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
