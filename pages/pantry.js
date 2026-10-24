// /structr/html/pantry: the stock on hand now and when it expires, soonest first, as mealplanner/inventory.py
// works them out: the latest weighing less every use since (current_magnitude), and the shelf life of
// its perishability where it is kept, from when it was bought or first weighed (instance_expiration).

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
