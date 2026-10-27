// Instructions written from a recipe's steps (mealplanner/instructions.py): one plain sentence of our
// own per step, from its facts, word for word as the Python writes them; and a Plan's steps read back
// as plain data, as recipe_import.export_plan reads them (data-model.md J35). The recipe page shows
// them; the writeInstructions method writes sentences for steps given as data, so tools/
// check_instructions.py can compare the two writers on any steps at all.

const VERBS = {
  "Boiling": "Boil", "Simmering": "Simmer", "Braising": "Braise", "Stir-Frying": "Stir-fry", "Searing": "Sear",
  "Sauteing": "Sauté", "Roasting": "Roast", "Baking": "Bake", "Broiling": "Broil", "Soaking": "Soak",
  "Marinating": "Marinate", "Mixing": "Mix", "Chopping": "Chop", "Dicing": "Dice", "Mincing": "Mince",
  "Slicing": "Slice", "Grating": "Grate", "Peeling": "Peel", "Mashing": "Mash",
};
const COUNTED_UNITS = ["each", "whole", "count"];

// instructions.number: to three places at most, half up, then the shortest form of that double
function writtenNumber(x) {
  return String(Math.floor(x * 1000 + 0.5) / 1000);
}

// instructions.join
function joinWords(items) {
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}

// instructions.ingredient
function ingredientWords(ing, made) {
  const name = String(ing.food).toLowerCase();
  if (made[ing.food]) return "the " + name;
  const unit = COUNTED_UNITS.indexOf(ing.unit) >= 0 ? "" : " " + (ing.unit || "");
  const alternatives = [];
  for (const sub of ing.substitutes || []) {                // what may stand in, by its ratio; never one ruled out
    if (sub.never) continue;
    const scaled = ing.amount == null || sub.ratio === 1 ? "" : writtenNumber(ing.amount * sub.ratio) + unit + " ";
    alternatives.push("or " + scaled + String(sub.food).toLowerCase());
  }
  const other = alternatives.length ? " (" + alternatives.join(", ") + ")" : "";
  if (ing.amount == null) return name + other + (ing.optional ? ", to taste" : "");
  return writtenNumber(ing.amount) + unit + " " + name + other + (ing.optional ? " (optional)" : "");
}

// instructions.sentence: step i (from 1), knowing what the steps before it made
function stepSentence(i, step, made) {
  const what = joinWords(step.inputs.map((ing) => ingredientWords(ing, made)));
  const verb = VERBS[step.method || ""];
  const parts = [verb ? verb + " " + what : step.label.slice(0, 1).toUpperCase() + step.label.slice(1) + ": " + what];
  const heated = {};
  for (const h of step.heat) heated[h.tool] = h;
  for (const tool of step.equipment) {
    const setting = heated[tool];
    if (setting && setting.temp != null) parts.push("in the " + tool.toLowerCase() + " at " + writtenNumber(setting.temp) + " °" + setting.unit);
    else if (setting) parts.push("on the " + tool.toLowerCase() + " over " + setting.level + " heat");
  }
  const plain = step.equipment.filter((tool) => !heated[tool]).map((tool) => tool.toLowerCase());
  if (plain.length) parts.push("using the " + joinWords(plain));
  const done = [];
  if (step.until) done.push(step.until.toLowerCase().indexOf("until ") === 0 ? step.until.slice(6) : step.until);
  if (step.inside) done.push(writtenNumber(step.inside[0]) + " °" + step.inside[1] + " inside");
  if (done.length) parts.push("until " + done.join(" and "));
  let text = parts.join(" ");
  const total = (step.minutes || 0) + (step.wait_minutes || 0);
  if (total) {
    text += ", about " + writtenNumber(total) + " minutes";
    if (step.minutes && step.wait_minutes) text += ", " + writtenNumber(step.minutes) + " of them hands-on";
  }
  if (i > 1 && step.after != null && step.after.indexOf(i - 1) < 0) text = "Meanwhile, " + text.slice(0, 1).toLowerCase() + text.slice(1);
  return text + ".";
}

// instructions.instructions
function stepSentences(steps) {
  const out = [], made = {};
  steps.forEach((step, k) => {
    out.push(stepSentence(k + 1, step, made));
    made[step.makes] = true;
  });
  return out;
}

// recipe_import.export_plan, as instructions.as_data has it: a Plan's steps in order, with their facts
const TEMP_SAID = {degF: "F", degC: "C"};
// recipe_import._step_index, _input_index and the equipment number: after the plan's name, and after
// the last " input " or " equipment "
const stepNumber = (step, plan) => Number(String(step.name).slice((plan.name + " step ").length).split(" ")[0]);
const lastNumber = (name, word) => { const s = String(name), k = s.lastIndexOf(" " + word + " "); return Number(s.slice(k + word.length + 2).split(" ")[0]); };
function requirementsOf(spec) {
  const out = {};
  for (const req of spec.hasStateRequirement || []) {
    const kind = req.targetsProperty ? req.targetsProperty.name : null;
    const q = req.expectedValueQty;
    if (kind) out[kind] = [req.expectedValueLiteral || null, q ? q.value : null, q ? (TEMP_SAID[q.unit] || q.unit) : null];
  }
  return out;
}
function planSteps(plan) {
  const steps = (plan.steps || []).slice().sort((a, b) => stepNumber(a, plan) - stepNumber(b, plan));
  const numberOf = {};
  for (const s of steps) numberOf[s.id] = stepNumber(s, plan);
  const ordered = steps.some((s) => (s.isPrecededBy || []).length);
  return steps.map((step) => {
    const index = numberOf[step.id];
    const specs = (step.hasSpecification || []).slice().sort((a, b) => (String(a.name) < String(b.name) ? -1 : String(a.name) > String(b.name) ? 1 : 0));
    const out = {label: String(step.name).slice((plan.name + " step " + index + " -- ").length),
                 method: step.instanceOf ? step.instanceOf.name : null, makes: null, equipment: [], inputs: [], heat: [],
                 minutes: step.hasWorkingTime ? step.hasWorkingTime.value : null,
                 wait_minutes: step.hasWaitingTime ? step.hasWaitingTime.value : null, after: null, until: null, inside: null};
    const tools = [], inputs = [];
    for (const spec of specs) {
      const wanted = requirementsOf(spec);
      const name = spec.specifies ? spec.specifies.name : null;
      if (spec.hasParticipationRole === "output") {
        out.makes = name;
        if (wanted["Doneness"]) out.until = wanted["Doneness"][0];
        if (wanted["Temperature"]) out.inside = [wanted["Temperature"][1], wanted["Temperature"][2]];
      } else if (spec.hasParticipationRole === "instrument") {
        const k = lastNumber(spec.name, "equipment");
        tools.push([k, name]);
        if (wanted["Temperature"]) out.heat.push([k, {tool: name, temp: wanted["Temperature"][1], unit: wanted["Temperature"][2], level: null}]);
        else if (wanted["Heat Level"]) out.heat.push([k, {tool: name, temp: null, unit: null, level: wanted["Heat Level"][0]}]);
      } else {
        const q = spec.hasSpecifiedQuantity;
        const rules = (spec.hasSubstitutionRule || []).slice().sort((x, y) => lastNumber(x.name, "or") - lastNumber(y.name, "or"))
          .map((r) => ({food: r.candidateType ? r.candidateType.name : null, ratio: r.substitutionRatio == null ? 1 : r.substitutionRatio,
                        never: !!r.isExcluded}));
        inputs.push([lastNumber(spec.name, "input"), {food: name, amount: q ? q.value : null, unit: q ? q.unit : null,
                                                      optional: !!spec.isOptional, substitutes: rules}]);
      }
    }
    const byFirst = (a, b) => a[0] - b[0];
    out.equipment = tools.sort(byFirst).map((t) => t[1]);
    out.heat = out.heat.sort(byFirst).map((h) => h[1]);
    out.inputs = inputs.sort(byFirst).map((x) => x[1]);
    if (ordered) {
      const numbers = (step.isPrecededBy || []).map((s) => numberOf[s.id]).filter((n) => n != null).sort((a, b) => a - b);
      const usual = index > 1 ? [index - 1] : [];
      out.after = numbers.join(",") === usual.join(",") ? null : numbers;
    }
    return out;
  });
}
