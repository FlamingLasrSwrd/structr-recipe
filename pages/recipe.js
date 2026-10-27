// /structr/html/recipe/<Plan id>: one recipe version, as tools/import_recipe.py loaded it: its facts, its
// ingredients and amounts step by step (a source's instructions are not stored), instructions of our own
// written from the steps' facts (pages/lib/75_instructions.js), and every stored figure per serving.

function stepIndex(step) {
  const m = / step (\d+)( -- |$)/.exec(String(step.name || ""));
  return m ? Number(m[1]) : 0;
}

const plan = $.current && $.current.type === "Plan" ? $.current : null;
let html = nav("recipes") + runBooking(REQUEST_ACTIONS);
const data = {};
if (!plan) {
  html += "<h1>Recipe</h1><p>No such recipe. Pick one from <a href=\"/structr/html/recipes\">the recipe book</a>.</p>";
} else {
  const identity = plan.specializationOf;
  const source = identity ? (identity.identifiers || []).find((i) => String(i.name).endsWith(" source")) : null;
  html += "<h1>" + esc(plan.name) + "</h1><dl>"
    + (source ? "<dt>From</dt><dd><a href=\"" + esc(source.identifierValue) + "\">" + esc(source.identifierValue) + "</a></dd>" : "")
    + "<dt>Meals</dt><dd>" + esc(identity ? (identity.hasMealType || []).map((c) => c.name).sort().join(", ") : "") + "</dd>"
    + "<dt>Makes</dt><dd>" + number(plan.hasRecipeYield ? plan.hasRecipeYield.value : null, 2) + " servings</dd>"
    + "<dt>Time</dt><dd>" + number(plan.estimatedDurationMinutes, 0) + " minutes"
    + (plan.makeAheadHours ? ", then " + number(plan.makeAheadHours) + " h made ahead" : "") + "</dd>"
    + "<dt>Difficulty</dt><dd>" + esc(plan.difficultyRating || "not stated") + "</dd></dl>";

  // "Cook in the week of ...": a request on the next week to plan (mealplanner/requests.py)
  if (identity) {
    const start = nextWeekStart(), asked = requestedIn(start).some((r) => r.id === identity.id);
    data.request = {week: start, asked: asked};
    html += "<form class=\"inline\" action=\"/structr/html/recipe/" + esc(plan.id) + "\">"
      + "<input type=\"hidden\" name=\"do\" value=\"" + (asked ? "withdraw" : "ask") + "\">"
      + "<input type=\"hidden\" name=\"recipe\" value=\"" + esc(identity.id) + "\">"
      + "<input type=\"hidden\" name=\"week\" value=\"" + esc(start) + "\">"
      + "<input type=\"hidden\" name=\"token\" value=\"" + newToken() + "\">"
      + (asked ? "Asked for in the week of " + esc(weekWords(start)) + ". <button>Don't cook it then</button>"
               : "<button title=\"The planner cooks it at least once that week, choosing the day\">Cook in the week of "
                 + esc(weekWords(start)) + "</button>")
      + "</form>";
  }

  data.ingredients = [];
  const steps = (plan.steps || []).slice().sort((a, b) => stepIndex(a) - stepIndex(b));
  for (const step of steps) {
    const specs = (step.hasSpecification || []).slice().sort((a, b) => String(a.name).localeCompare(String(b.name), "en", {numeric: true}));
    const label = String(step.name || "").split(" -- ").slice(1).join(" -- ") || "step " + stepIndex(step);
    html += "<h3>" + esc(label) + (step.instanceOf ? " <small>(" + esc(step.instanceOf.name) + ")</small>" : "") + "</h3><ul>";
    for (const spec of specs.filter((s) => s.hasParticipationRole === "input")) {
      const q = spec.hasSpecifiedQuantity;
      const amount = q && q.value != null ? number(q.value, 2) + " " + esc(q.unit || "") + " " : "";
      data.ingredients.push({food: spec.specifies ? spec.specifies.name : null, amount: q ? q.value : null, unit: q ? q.unit : null});
      html += "<li>" + amount + esc(spec.specifies ? spec.specifies.name : "?") + (spec.isOptional ? " <i>(optional)</i>" : "") + "</li>";
    }
    const tools = specs.filter((s) => s.hasParticipationRole === "instrument").map((s) => s.specifies ? s.specifies.name : "?");
    const makes = specs.filter((s) => s.hasParticipationRole === "output").map((s) => s.specifies ? s.specifies.name : "?");
    html += "</ul>" + (tools.length ? "<p class=\"note\">With: " + esc(tools.join(", ")) + "</p>" : "")
      + (makes.length ? "<p class=\"note\">Makes: " + esc(makes.join(", ")) + "</p>" : "");
  }

  // instructions of our own, written from the steps' facts (mealplanner/instructions.py; J35)
  data.instructions = stepSentences(planSteps(plan), capabilityBearers(plan));
  html += "<h2>How to make it</h2><ol class=\"instructions\">" + data.instructions.map((line) => "<li>" + esc(line) + "</li>").join("")
    + "</ol><p class=\"note\">Written here from the steps' facts, not the source's words.</p>";

  const stored = (plan.servingProfiles || []).filter((p) => p.basis === "per_serving" && p.forNutrient)
    .sort((a, b) => String(a.forNutrient.name).localeCompare(String(b.forNutrient.name)));
  data.figures = stored.map((p) => ({nutrient: p.forNutrient.name, amount: p.amount, unit: p.unit, provenance: p.provenance}));
  html += "<h2>Per serving</h2>";
  if (!stored.length) {
    html += "<p>No figures stored: <code>tools/calculate_recipe_nutrition.py</code> works them out.</p>";
  } else {
    html += "<table><thead><tr><th>Nutrient</th><th>Amount</th><th>Rests on</th></tr></thead><tbody>"
      + stored.map((p) => "<tr><td>" + esc(p.forNutrient.name) + "</td><td class=\"num\">"
        + (p.amount == null ? "?" : number(p.amount, p.amount >= 100 ? 0 : 2) + " " + esc(p.unit)) + "</td><td>"
        + esc(p.provenance === "calculated" && p.amount != null ? "published data" : p.source || p.provenance) + "</td></tr>").join("")
      + "</tbody></table>";
  }
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
