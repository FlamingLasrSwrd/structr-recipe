// /structr/html/alternatives/<MealPlan id>?food=<food>[&prices=<price level>]: what could take the place of a
// shopping line's food in the week's meals still to cook, best first, as mealplanner/alternatives.py lists
// them (pages/lib/92_substitutes.js, alternativesFor): the same food in another size or kind; what the recipes
// themselves say may stand in; foods beside it, not checked against a recipe; or the meals planned again.
// Each with what it does to the week's cost (per gram, before packages) and to each nutrient a target is
// about, in the dishes as cooked.
//
// "Bought this instead" (or "Bought something else", any food by name) books the purchase, as the pantry's
// Buy does, and has the meals that needed the listed food use the bought one, for those meals only: by the
// recipe's own rule where it has one, else one to one by weight (do=instead, SWAP_ACTIONS; substitutes.py).
// The week page names each swap, with Undo.

const said = runBooking(SWAP_ACTIONS);
const hidden = (fields) => Object.keys(fields).map((k) => "<input type=\"hidden\" name=\"" + k + "\" value=\"" + esc(fields[k]) + "\">").join("");
const options = (values, chosen) => values.map((v) => "<option" + (v === chosen ? " selected" : "") + ">" + esc(v) + "</option>").join("");
const money = (x) => (x < 0 ? "−$" : "+$") + Math.abs(x).toFixed(2);
const signed = (x, places) => (x < 0 ? "−" : "+") + number(Math.abs(x), places);

function servedFile(name) {
  const file = $.find("File", {name: name}).filter((f) => f.path === "/mealplanner/" + name)[0];
  if (!file) return null;
  return file.path + "?v=" + (file.checksum || (file.lastModifiedDate ? new Date(file.lastModifiedDate).getTime() : 0));
}

const week = chosenWeek();
const asked = String($.request.listed || $.request.food || "").trim();   // after "bought instead", food is what was bought
const levelName = $.request.prices || "Home prices";
const data = {food: asked, grams: 0, meals: [], options: []};
let html = nav("shopping") + "<h1>Alternatives</h1>" + said;
const found = asked ? $.find("DomainType", {name: asked}) : [];
if (!week) {
  html += "<p>No week has been committed yet.</p>";
} else if (found.length !== 1) {
  html += "<p class=\"problem\">No food is named " + esc(asked) + ".</p>";
} else {
  const food = found[0], prices = priceTable(levelName), nutrients = targetedNutrients();
  const alts = alternativesFor(week, food, prices, nutrients), zone = weekZone(week);
  const entries = {};
  for (const e of week.hasEntry || []) entries[e.name] = e;
  const mealText = (name) => {
    const e = entries[name], start = e ? startOf(e) : null;
    return (start ? dayLabel(start, zone) + " " : "") + (e && e.references ? e.references.name : name);
  };
  html += "<h2>In place of " + esc(food.name) + "</h2><p><a href=\"/structr/html/shopping/" + esc(week.id) + "\">Back to the shopping list</a> for "
    + esc(week.name) + "</p>";
  if (!alts.meals.length) {
    html += "<p>No meal of this week still to cook needs " + esc(food.name) + ".</p>";
  } else {
    html += "<p class=\"note\">" + number(alts.grams, 0) + " g of it for " + alts.meals.map((m) => esc(mealText(m[0]))).join(", ")
      + ". Best first. Costs at " + esc(levelName) + (prices ? "" : " (no such price level)") + ", per gram as the recipes weigh it, before "
      + "rounding to packages; nutrients in the dishes as cooked.</p>";
    const storage = "<select name=\"storage\">" + options(STORAGE, "Fridge") + "</select>";
    const buyForm = (o) => "<form class=\"inline\" action=\"/structr/html/alternatives/" + esc(week.id) + "\">"
      + hidden({do: "instead", token: newToken(), week: week.id, listed: food.name, food: o.food,
                entries: o.meals.map((m) => entries[m] ? entries[m].id : "").join(",")})
      + "<input name=\"amount\" type=\"number\" step=\"any\" min=\"0\" required size=\"6\" value=\"" + esc(Math.ceil(o.grams)) + "\">"
      + "<select name=\"unit\">" + options(UNITS, "g") + "</select>" + storage + "<button>Bought this instead</button></form>";
    html += "<table class=\"alternatives\"><thead><tr><th>Instead</th><th>For</th><th class=\"num\">Cost</th><th>Nutrients</th><th></th></tr></thead><tbody>";
    for (const o of alts.options) {
      let what, cost = "", nut = "", act = "";
      if (o.kind === "same") {
        what = "The same food, any size or brand" + (o.kinds.length ? ", or a kind of it: " + esc(o.kinds.join(", ")) : "")
          + (o.have > 0 ? " <small>(have " + number(o.have, 0) + " g)</small>" : "");
        nut = "no change";
      } else if (o.kind === "replan") {
        what = "None of these: plan the meals again without it";
        act = "<a href=\"/structr/html/week/" + esc(week.id) + "\">Skip them on the week page</a>, then plan the free meals (<code>tools/plan_week.py</code>)";
      } else {
        what = "<b>" + esc(o.food) + "</b> " + (o.kind === "recipe"
          ? "<small>the recipe's own" + (o.ratio != null && o.ratio !== 1 ? ", " + number(o.ratio, 2) + " for 1" : "") + "</small>"
          : "<small class=\"estimated\">one to one by weight, not checked against the recipe</small>")
          + " " + number(o.grams, 0) + " g" + (o.have > 0 ? " <small>(have " + number(o.have, 0) + " g)</small>" : "");
        cost = o.effect.cost == null ? "?" : money(o.effect.cost);
        const changed = o.effect.nutrients.filter((n) => n[2] != null && Math.abs(n[2]) >= 0.05)
          .map((n) => esc(n[0]) + " " + signed(n[2], 1) + " " + esc(n[1]));
        const unknown = o.effect.nutrients.filter((n) => n[2] == null).map((n) => esc(n[0]));
        nut = (changed.length ? changed.join(", ") : o.effect.nutrients.length ? "no change" : "")
          + (unknown.length ? (changed.length ? "; " : "") + "not known: " + unknown.join(", ") : "");
        act = buyForm(o);
      }
      html += "<tr><td>" + what + "</td><td>" + o.meals.map((m) => esc(mealText(m))).join(", ") + "</td><td class=\"num\">" + cost
        + "</td><td class=\"note\">" + nut + "</td><td>" + act + "</td></tr>";
    }
    html += "</tbody></table>";
    // any other food, by name: the pantry's food picker searches as you type, where it is installed
    const products = productIds();
    const foods = (($.find("TypeHierarchy", {name: "Food Identity"})[0] || {}).domainTypes || [])
      .filter((t) => (t.children || []).every((c) => products[c.id])).map((t) => t.name).sort();
    const picker = servedFile(FOODS_FILE);
    html += "<details class=\"buy\" open><summary>Bought something else</summary>"
      + "<form class=\"inline\" action=\"/structr/html/alternatives/" + esc(week.id) + "\">"
      + hidden({do: "instead", token: newToken(), week: week.id, listed: food.name})
      + "<input name=\"food\" list=\"foods\" required placeholder=\"what you bought\" size=\"24\">"
      + "<input name=\"amount\" type=\"number\" step=\"any\" min=\"0\" required size=\"6\" placeholder=\"amount\">"
      + "<select name=\"unit\">" + options(UNITS, "g") + "</select>" + storage + "<button>Bought this instead</button></form>"
      + "<p class=\"note\">For every meal above. It goes into the pantry, and those meals use it in place of " + esc(food.name)
      + ", one to one by weight unless the recipe says otherwise.</p>"
      + "<datalist id=\"foods\">" + foods.map((f) => "<option value=\"" + esc(f) + "\">").join("") + "</datalist>"
      + (picker ? "<script src=\"" + esc(picker) + "\" defer></script>" : "") + "</details>";
  }
  data.food = alts.food;
  data.grams = alts.grams;
  data.meals = alts.meals;
  data.options = alts.options.map((o) => ({kind: o.kind, food: o.food, meals: o.meals, grams: o.grams, have: o.have, ratio: o.ratio,
                                           kinds: o.kinds, checked: o.checked, effect: o.effect}));
}
$.print(html + "<script type=\"application/json\" id=\"page-data\">" + JSON.stringify(data).replace(/</g, "\\u003c") + "</script>");
