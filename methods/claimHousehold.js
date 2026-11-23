// claimHousehold: make what belongs to the instance's household private to it, and what belongs to one of
// its people private to that person, leaving shared knowledge shared (docs/verification-and-sharing.md
// §3.4, "Who owns what"; Path S stage 5). For the tools' admin account only: scripts/50a and the tools that
// write a household's data call it through mealplanner/ownership.py.
//
// What is whose is worked out from the graph each time, never stored apart from the grants it leaves:
//   - a person's own: their nutrition targets and exclusions (forPerson) and their baseline recipes
//     (hasBaseline), with what those hold;
//   - the household's: its weeks (MealPlan), every booking and cook (Process), its stock (portions and
//     containers), its kitchen (UtensilSet), its pantry's stock levels (StockPolicy), its shopping lists,
//     every other target, its own price and package levels (`levels`), and every recipe that is not one of
//     the public ones (`shared`, the names in data/recipes/), with what each holds;
//   - everything else is shared: the vocabulary, profiles, public levels and recipes, products and barcodes.
// "What each holds" follows only the relationships of PARTS below, so a reference to shared vocabulary (a
// food, a kind, a recipe a week cooks) is never followed.
//
// A household's node is visible to no one by its flags and granted read, write and delete to the
// household's Group, as the methods' own bookings write it. A person's node is granted read, write and
// delete to that Person and read to the household, so the others at the table see what a shared meal
// must meet but do not change it.
//
// For an instance of one household. With several, which is whose cannot be read off the graph for data
// made before households kept theirs apart, so it refuses, and each writer must write privately itself.
//
// Arguments: household (the Household's id), shared (recipe names), levels (DomainType names), limit (most
// nodes to change in this call, default 500), check (true: change nothing). Answers {household, changed,
// remaining, counts: {type: n}, problem}; called again until remaining is 0.

const p = $.methodParameters || {};
if (!$.me || $.me.isAdmin !== true) return {problem: "claimHousehold is for the tools' admin account"};
const households = $.find("Household");
if (households.length !== 1) return {problem: "this instance has " + households.length + " households: ownership is worked out for one"};
const household = households[0];
if (p.household && p.household !== household.id) return {problem: "no such household"};

// The relationships along which a node holds what is its own (data-model.md; the schema modules' target
// json names, hard rule 6)
const PARTS = {
  MealPlan: ["isAbout", "hasEntry", "acquisitionLists"],
  MealPlanEntry: ["isAbout", "hasPlannedConsumption", "hasShare", "reservationRole"],
  MealShare: ["hasPlannedConsumption"],
  Process: ["occupiesTemporalRegion", "qualifiedUsage", "qualifiedGeneration", "thingsBegunDuring"],
  Allocation: ["hasActualQuantity"],
  PortionOfSubstance: ["locatedIn", "bearerOf"],
  DiscreteWholeItem: ["locatedIn", "bearerOf"],
  ContainerObject: ["bearerOf"],
  EquipmentObject: ["bearerOf"],
  UtensilSet: ["hasMemberPart"],
  Quality: ["measurements"],
  Measurement: ["wasDerivedFrom"],
  StockPolicy: ["hasReorderThreshold", "hasTargetLevel"],
  NutritionTarget: ["hasTargetRange"],
  RecipeIdentity: ["planVersions", "identifiers"],
  Plan: ["steps", "hasRecipeYield", "servingProfiles"],
  Step: ["hasSpecification", "hasWorkingTime", "hasWaitingTime"],
  Specification: ["hasSpecifiedQuantity", "hasStateRequirement", "hasSubstitutionRule"],
  StateRequirement: ["expectedValueQty"],
  DomainType: ["defaultSpecifications"],            // a household's own level only: see levelRoots
  DefaultSpecification: ["hasValue"],
};
// Never anyone's own, whatever points at them
const SHARED_TYPES = {TypeHierarchy: 1, Concept: 1, ConceptScheme: 1, Person: 1, Household: 1, User: 1, Group: 1};

const list = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);
const memberIds = {};
for (const m of list(household.members)) memberIds[m.id] = m;

const owner = {};          // node id -> {node, person (a Person, or null for the household)}
const order = [];
function visit(node, person, root) {
  if (!node || !node.id || owner[node.id] || SHARED_TYPES[node.type]) return;
  if (node.type === "DomainType" && !root) return;                  // a food, a kind: shared vocabulary
  owner[node.id] = {node: node, person: person};
  order.push(node.id);
  for (const key of PARTS[node.type] || []) {
    for (const child of list(node[key])) {
      if (node.type === "DomainType" && child.forType && child.forType.id !== node.id) continue;
      visit(child, person, false);
    }
  }
}

// A person's own first, so that what they hold stays theirs
for (const person of Object.keys(memberIds).map((id) => memberIds[id])) {
  for (const target of $.find("NutritionTarget")) if (target.forPerson && target.forPerson.id === person.id) visit(target, person, true);
  for (const rule of $.find("ExclusionConstraint")) if (rule.forPerson && rule.forPerson.id === person.id) visit(rule, person, true);
  for (const plan of list(person.hasBaseline)) visit(plan.specializationOf || plan, person, true);
}
// then the household's
const sharedRecipes = {};
for (const name of list(p.shared)) sharedRecipes[name] = true;
const levelNames = {};
for (const name of list(p.levels)) levelNames[name] = true;
for (const type of ["MealPlan", "Process", "PortionOfSubstance", "DiscreteWholeItem", "ContainerObject", "UtensilSet",
                    "StockPolicy", "AcquisitionList", "NutritionTarget", "ExclusionConstraint"]) {
  for (const node of $.find(type)) if (node.type === type) visit(node, null, true);
}
for (const recipe of $.find("RecipeIdentity")) if (!sharedRecipes[recipe.name]) visit(recipe, null, true);
for (const name of Object.keys(levelNames)) for (const level of $.find("DomainType", {name: name})) visit(level, null, true);

// A value that a shared default also holds is not the household's to take
const keep = order.filter((id) => {
  const node = owner[id].node;
  if (node.type !== "QuantitySpecification") return true;
  return list(node.defaultSpecification).every((d) => owner[d.id]);
});

// What is not yet as it should be: shared still, or a person's node the household may still change
const due = keep.filter((id) => {
  const {node, person} = owner[id];
  if (node.visibleToAuthenticatedUsers !== false || node.visibleToPublicUsers !== false) return true;
  if (!$.isAllowed(household, node, "read")) return true;
  if (person) return !$.isAllowed(person, node, "write") || $.isAllowed(household, node, "write");
  return !$.isAllowed(household, node, "write");
});

const limit = Math.max(1, Number(p.limit) || 500), counts = {};
let changed = 0;
for (const id of due.slice(0, p.check ? due.length : limit)) {
  const {node, person} = owner[id];
  counts[node.type] = (counts[node.type] || 0) + 1;
  if (p.check) continue;
  node.visibleToAuthenticatedUsers = false;
  node.visibleToPublicUsers = false;
  if (person) {
    $.grant(person, node, "read, write, delete");
    $.revoke(household, node, "write, delete");
    $.grant(household, node, "read");
  } else {
    $.grant(household, node, "read, write, delete");
  }
  changed++;
}
return {household: household.name, changed: changed, remaining: due.length - changed, owned: keep.length, counts: counts,
        problem: null};
