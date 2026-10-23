// /structr/html/pantry: the stock on hand now and when it expires, soonest first, as mealplanner/inventory.py
// works them out: the latest weighing less every use since (current_magnitude), and the shelf life of
// its perishability where it is kept, from when it was bought or first weighed (instance_expiration).

const NOW = new Date();

// inventory.mass_quality
const massQuality = (portion) => (portion.bearerOf || []).find((q) => q.type === "Quality" && q.hasKind && q.hasKind.name === "Mass") || null;

// inventory._baselines: observed or imputed Measurements with a time, oldest first
const baselines = (quality) => (quality.measurements || []).filter((m) => (m.status === "observed" || m.status === "imputed") && m.hasTime)
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
  const known = baselines(quality).filter(([t]) => t <= NOW);
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

// inventory.instance_expiration: days until it expires (negative: expired), or null if it cannot be told
const typeId = (name) => { const t = $.find("DomainType", {name: name})[0]; return t ? t.id : null; };
function daysUntilExpiry(portion) {
  const perishability = portion.hasPerishabilityType, quality = massQuality(portion);
  if (!perishability || !quality) return [null, "no perishability"];
  const weighed = baselines(quality).filter(([t]) => t <= NOW);
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
  const kept = (box && box.hasStorageCondition && box.hasStorageCondition.name) || "Fridge";
  const shelf = resolveDefault(perishability, "ShelfLife", [typeId(kept), typeId(opened)]);
  const q = shelf && shelf.hasValue;
  if (!q || q.unit !== "days" || q.value == null) return [null, "no shelf life for " + perishability.name + ", " + kept + ", " + opened];
  return [(started.getTime() + q.value * 86400e3 - NOW.getTime()) / 86400e3, kept + ", " + opened];
}

const rows = [];
for (const portion of $.find("PortionOfSubstance").concat($.find("DiscreteWholeItem"))) {
  const level = onHand(portion);
  if (level == null) continue;                                      // no weighing yet: not known to exist
  const [days, why] = daysUntilExpiry(portion);
  rows.push({portion: portion, food: portion.instanceOf ? portion.instanceOf.name : portion.name, level: level, days: days, why: why});
}
rows.sort((a, b) => (a.days == null) - (b.days == null) || (a.days - b.days) || a.food.localeCompare(b.food));

let html = nav("pantry") + "<h1>Pantry</h1><p class=\"note\">" + rows.length + " foods on hand, "
  + rows.filter((r) => r.days != null).length + " with a known shelf life. Soonest to expire first.</p>"
  + "<table><thead><tr><th>Food</th><th>On hand</th><th>Weighed</th><th>Expires</th></tr></thead><tbody>";
const data = [];
for (const r of rows) {
  const told = Array.isArray(r.level);
  const grams = told ? r.level[0] : null;
  data.push({portion: r.portion.name, grams: grams, days: r.days});
  const expires = r.days == null ? "<span class=\"note\">unknown: " + esc(r.why) + "</span>"
    : (r.days < 0 ? "<span class=\"above_max\">expired " + number(-r.days, 0) + " days ago</span>"
      : esc(dayLabel(new Date(NOW.getTime() + r.days * 86400e3), "UTC")) + " <small>(" + number(r.days, 0) + " days; " + esc(r.why) + ")</small>");
  html += "<tr><td>" + esc(r.food) + "</td><td class=\"num\">" + (told ? number(grams, 0) + " g" : "<span class=\"note\">" + esc(r.level) + "</span>")
    + "</td><td>" + (told ? esc(dayLabel(r.level[2], "UTC")) + " <small>(" + esc(r.level[1].status) + ")</small>" : "") + "</td><td>" + expires + "</td></tr>";
}
html += "</tbody></table><p class=\"note\">Imputed: an amount from the pantry profile, not a weighing.</p>";
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
