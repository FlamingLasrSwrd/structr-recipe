// /structr/html/recipes[?meal=<meal type>][&page=<n>]: the recipe book, every version the planner may
// choose from (planning/extract.build_problem's book: not a baseline, not retired), PAGE_SIZE at a time,
// with its stored figures per serving for the nutrients the targets are about (J28).
//
// Following a relationship costs about 1.8 ms in a page script (measured, 2026-10-22), so a book of a
// thousand recipes is read sparingly: the meal filter through the meal type's own list of recipes, the
// facts only for the recipes shown, and each nutrient's figures in one query, matched to their recipe
// by the name tools/calculate_recipe_nutrition.py gives them ("<recipe> -- <nutrient> per serving").

const PAGE_SIZE = 100;
const SHOWN = ["Energy", "Protein", "Fiber, total dietary", "Sodium, Na"];

// recipe_nutrition.targeted_nutrients: {nutrient id: [nutrient, unit]}, the unit of the first target by name
function targeted() {
  const out = {};
  for (const t of $.find("NutritionTarget").sort((a, b) => String(a.name).localeCompare(String(b.name)))) {
    const n = t.forNutrient, r = t.hasTargetRange;
    if (n && r && !out[n.id] && NUTRIENT_UNITS[String(r.unit || "").trim().toLowerCase()]) out[n.id] = [n, r.unit];
  }
  return out;
}

// Each recipe's stored figure for one nutrient, by recipe name: one query, no relationship followed
function figuresFor(nutrient, unit) {
  const suffix = " -- " + nutrient.name + " per serving", out = {};
  for (const p of $.find("NutrientProfile", {basis: "per_serving", forNutrient: nutrient})) {
    const name = String(p.name || "");
    if (!name.endsWith(suffix)) continue;
    const plan = name.slice(0, -suffix.length);
    if (out[plan]) { out[plan] = "two"; continue; }                 // two stored for one nutrient: not read, as in Python
    const amount = p.amount == null ? null : convertNutrient(p.amount, p.unit, unit);
    out[plan] = {amount: amount, estimated: p.provenance === "estimated"};
  }
  return out;
}

const nutrients = targeted();
const columns = SHOWN.map((name) => Object.keys(nutrients).find((id) => nutrients[id][0].name === name)).filter(Boolean);
const meal = $.request.meal || null;
const pageNo = Math.max(1, parseInt($.request.page || "1", 10) || 1);

const mealConcepts = $.find("Concept").filter((c) => (c.taggedRecipes || []).length && c.inScheme && c.inScheme.name === "Meal Type")
  .sort((a, b) => String(a.name).localeCompare(String(b.name)));
const chosen = meal ? mealConcepts.find((c) => c.name === meal) : null;
const identities = meal ? (chosen ? chosen.taggedRecipes : []) : $.find("RecipeIdentity");
const baselines = new Set([].concat(...$.find("MealPlan").map((m) => m.hasBaseline || []), ...$.find("Person").map((p) => p.hasBaseline || []))
  .map((p) => p.id));
const book = [].concat(...identities.filter((i) => !i.isRetired).map((i) => i.planVersions || []))
  .filter((p) => !baselines.has(p.id)).sort((a, b) => String(a.name).localeCompare(String(b.name)));
const pages = Math.max(1, Math.ceil(book.length / PAGE_SIZE));
const shown = book.slice((pageNo - 1) * PAGE_SIZE, pageNo * PAGE_SIZE);
const figures = columns.map((id) => figuresFor(nutrients[id][0], nutrients[id][1]));

const link = (m, p) => "/structr/html/recipes?" + (m ? "meal=" + encodeURIComponent(m) + "&" : "") + "page=" + p;
let html = nav("recipes") + "<h1>Recipes</h1><p class=\"filters\">"
  + [meal ? "<a href=\"/structr/html/recipes\">All</a>" : "<b>All</b>"]
    .concat(mealConcepts.map((c) => c.name === meal ? "<b>" + esc(c.name) + "</b>" : "<a href=\"" + link(c.name, 1) + "\">" + esc(c.name) + "</a>"))
    .join(" · ") + " — " + book.length + " recipe" + (book.length === 1 ? "" : "s")
  + (pages > 1 ? ", page " + pageNo + " of " + pages + " " + (pageNo > 1 ? "<a href=\"" + link(meal, pageNo - 1) + "\">previous</a> " : "")
    + (pageNo < pages ? "<a href=\"" + link(meal, pageNo + 1) + "\">next</a>" : "") : "") + "</p>"
  + "<table><thead><tr><th>Recipe</th><th>Meals</th><th>Minutes</th><th>Difficulty</th><th>Servings</th>"
  + columns.map((id) => "<th>" + esc(nutrients[id][0].name) + "<br><small>" + esc(nutrients[id][1]) + " a serving</small></th>").join("")
  + "</tr></thead><tbody>";
const data = [];
for (const plan of shown) {
  const row = columns.map((id, k) => {
    const found = figures[k][plan.name];
    if (found && found !== "two") return found;
    const own = found === "two" ? null : servingFigure(plan, id, nutrients[id][1]);   // a recipe renamed since: its own list
    return own ? {amount: own.amount, estimated: own.estimated} : null;
  });
  const identity = plan.specializationOf;
  const mealTypes = identity ? (identity.hasMealType || []).map((c) => c.name).sort() : [];
  data.push({recipe: plan.name, figures: Object.fromEntries(columns.map((id, k) => [nutrients[id][0].name, row[k] ? row[k].amount : null]))});
  html += "<tr><td><a href=\"/structr/html/recipe/" + plan.id + "\">" + esc(plan.name) + "</a></td><td>" + esc(mealTypes.join(", ")) + "</td><td>"
    + number(plan.estimatedDurationMinutes, 0) + (plan.makeAheadHours ? " <span class=\"ahead\">+" + number(plan.makeAheadHours) + " h ahead</span>" : "")
    + "</td><td>" + esc(plan.difficultyRating || "") + "</td><td>" + number(plan.hasRecipeYield ? plan.hasRecipeYield.value : null, 2) + "</td>"
    + row.map((f) => "<td class=\"num" + (f && f.estimated ? " estimated" : "") + "\">"
      + (f == null ? "<span title=\"not stored: tools/calculate_recipe_nutrition.py\">–</span>" : f.amount == null ? "?" : number(f.amount, f.amount >= 100 ? 0 : 1)) + "</td>").join("")
    + "</tr>";
}
html += "</tbody></table><p class=\"note\">Italics: the figure rests on an estimate. ?: unknown.</p>";
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
