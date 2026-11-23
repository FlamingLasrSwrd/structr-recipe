"""Who owns what (methods/claimHousehold.js, mealplanner/ownership.py; docs/verification-and-sharing.md §3.4,
"Who owns what"). The method runs in node or gjs, where either is installed, over a stand-in graph whose
grants answer $.isAllowed as Structr's did when probed (a grant to a household's Group reaches its members);
scripts/50a and tools/check_households.py run it on an instance.

The household "Home" has two people, Jamie and Alex. The graph holds, worked out by hand:
  Jamie's own: a target with its range, an exclusion, and the baseline recipe "Daily supplements" (identity,
    plan, step, ingredient, its amount): 8 nodes;
  the household's: a target with no person and its range; a week, its time, a meal, its time and servings,
    a share for Jamie and its servings; a purchase, its time, its draw and the draw's amount, the portion it
    bought, its container, its mass, the weighing and a weighing imputed from a value; the private recipe
    "Stew" (identity, source, plan, yield, step, ingredient, its amount, its stored nutrition); the
    household's price level, its price and the price's value: 29 nodes;
  shared: the food Eggs, the public recipe Bruschetta and all it holds, the public price level and its price,
    and the value an imputed weighing was derived from, which a shared default holds.
"""

import json
import pathlib
import unittest

from mealplanner import ownership
from tests.test_signed_out import ENGINE, javascript

ROOT = pathlib.Path(__file__).resolve().parent.parent
METHOD = (ROOT / "methods" / "claimHousehold.js").read_text()

GRAPH = r"""
var N = {}, seq = 0, all = [];
function node(type, name, props) {
  var n = Object.assign({id: "id" + (++seq), type: type, name: name, visibleToAuthenticatedUsers: true,
                         visibleToPublicUsers: false}, props || {});
  (N[type] = N[type] || []).push(n); all.push(n); return n;
}
function link(from, key, to, back) {
  if (Array.isArray(from[key])) from[key].push(to); else from[key] = to;
  if (back) { if (Array.isArray(to[back])) to[back].push(from); else if (to[back] == null) to[back] = from; else to[back] = [to[back], from]; }
}
var grants = {};                    // node id -> principal id -> {read, write, delete}
function allowed(principal, n, perm) {
  var g = grants[n.id] || {}, ids = [principal.id].concat((principal.groups || []).map(function (x) { return x.id; }));
  return ids.some(function (id) { return g[id] && g[id][perm]; });
}
function perms(text) { return text.split(",").map(function (s) { return s.trim(); }); }
var jamie = node("Person", "Jamie", {hasBaseline: []}), alex = node("Person", "Alex", {hasBaseline: []});
var home = node("Household", "Home", {members: [jamie, alex]});
jamie.groups = [home]; alex.groups = [home];
var $ = {me: ME, methodParameters: PARAMS,
  find: function (type, f) { return (N[type] || []).filter(function (n) { return !f || Object.keys(f).every(function (k) { return n[k] === f[k]; }); }); },
  isAllowed: function (p, n, perm) { return perms(perm).every(function (x) { return allowed(p, n, x); }); },
  grant: function (p, n, perm) { var g = grants[n.id] = grants[n.id] || {}; var s = g[p.id] = g[p.id] || {};
                                 perms(perm).forEach(function (x) { s[x] = true; }); },
  revoke: function (p, n, perm) { var s = (grants[n.id] || {})[p.id] || {}; perms(perm).forEach(function (x) { delete s[x]; }); }};

var eggs = node("DomainType", "Eggs");
function recipe(name) {
  var r = node("RecipeIdentity", name, {planVersions: [], identifiers: []});
  var plan = node("Plan", name + " v1", {steps: [], servingProfiles: []});
  link(plan, "specializationOf", r, "planVersions");
  var step = node("Step", name + " v1 step 1", {hasSpecification: []});
  link(plan, "steps", step);
  var spec = node("Specification", name + " v1 step 1 eggs", {specifies: eggs, hasStateRequirement: [], hasSubstitutionRule: []});
  link(step, "hasSpecification", spec);
  link(spec, "hasSpecifiedQuantity", node("QuantitySpecification", name + " eggs quantity"));
  return {identity: r, plan: plan};
}
var bruschetta = recipe("Bruschetta"), stew = recipe("Stew"), daily = recipe("Daily supplements");
link(stew.plan, "hasRecipeYield", node("QuantitySpecification", "Stew yield"));
link(node("Identifier", "Stew source"), "denotes", stew.identity, "identifiers");
link(node("NutrientProfile", "Stew protein per serving"), "servingOf", stew.plan, "servingProfiles");
link(bruschetta.plan, "hasRecipeYield", node("QuantitySpecification", "Bruschetta yield"));
jamie.hasBaseline.push(daily.plan);

var t1 = node("NutritionTarget", "Daily protein (Jamie)", {forPerson: jamie});
link(t1, "hasTargetRange", node("QuantitySpecification", "Daily protein (Jamie) range"));
node("ExclusionConstraint", "No peanuts (Jamie)", {forPerson: jamie});
var t2 = node("NutritionTarget", "Weekly fibre");
link(t2, "hasTargetRange", node("QuantitySpecification", "Weekly fibre range"));

var week = node("MealPlan", "Week of 2026-11-23", {hasEntry: [], isAbout: node("TemporalRegion", "the week")});
var dinner = node("MealPlanEntry", "Mon Dinner -- Stew v1", {references: stew.plan, hasShare: [],
  isAbout: node("TemporalRegion", "Mon dinner"), hasPlannedConsumption: node("QuantitySpecification", "Mon dinner servings")});
link(week, "hasEntry", dinner, "memberOf");
var share = node("MealShare", "Mon Dinner -- Jamie", {eatenBy: jamie, hasPlannedConsumption: node("QuantitySpecification", "Mon Jamie servings")});
link(dinner, "hasShare", share, "shareOf");

var buy = node("Process", "Purchase t1", {occupiesTemporalRegion: node("TemporalRegion", "Purchase t1 time"), qualifiedUsage: [], thingsBegunDuring: []});
var draw = node("Allocation", "Purchase t1 -- draw", {hasActualQuantity: node("Measurement", "Purchase t1 -- draw amount")});
link(buy, "qualifiedUsage", draw, "process");
var portion = node("PortionOfSubstance", "Purchase t1 -- Eggs", {instanceOf: eggs, bearerOf: [], locatedIn: node("ContainerObject", "Purchase t1 -- Eggs container")});
link(buy, "thingsBegunDuring", portion, "beginsToExistDuring");
var mass = node("Quality", "Purchase t1 -- Eggs mass Quality", {measurements: []});
link(portion, "bearerOf", mass, "inheresIn");
var weighed = node("Measurement", "Purchase t1 -- Eggs mass bought");
link(mass, "measurements", weighed, "isAboutQuality");

var priceRef = node("TypeHierarchy", "Price Reference");
function level(name, value) {
  var lv = node("DomainType", name, {hierarchy: priceRef, defaultSpecifications: []});
  var ds = node("DefaultSpecification", name + " -- Eggs", {forType: lv, keyedBy: [eggs]});
  lv.defaultSpecifications.push(ds);
  var q = node("QuantitySpecification", name + " -- Eggs price", {value: value});
  link(ds, "hasValue", q, "defaultSpecification");
  eggs.defaultSpecifications = (eggs.defaultSpecifications || []);
  return {level: lv, value: q};
}
level("Home prices", 0.4);
var publicLevel = level("US prices (BLS)", 0.5);
var derived = node("Measurement", "Purchase t1 -- Eggs mass assumed", {wasDerivedFrom: publicLevel.value});
link(mass, "measurements", derived, "isAboutQuality");
"""

ADMIN = {"name": "mealplanner-tools", "isAdmin": True}
PARAMS = {"shared": ["Bruschetta"], "levels": ["Home prices"]}


def run(calls=1, me=ADMIN, params=None, extra="", between=""):
    """The answers of `calls` calls in a row (`extra` run first, `between` before each call after the first),
    and then each node's visibility and grants, by name."""
    code = (GRAPH.replace("ME", json.dumps(me)).replace("PARAMS", json.dumps({**PARAMS, **(params or {})}))
            + extra + "\nvar answers = [];\nfor (var i = 0; i < " + str(calls) + "; i++) { if (i) { " + between + " }\nanswers.push((function () {\n"
            + METHOD + "\n})()); }\n"
            + "var nodes = {}; all.forEach(function (n) { var g = grants[n.id] || {}, who = {};"
            + " Object.keys(g).forEach(function (id) { var name = all.filter(function (x) { return x.id === id; })[0].name;"
            + " var ps = Object.keys(g[id]).filter(function (k) { return g[id][k]; }).sort(); if (ps.length) who[name] = ps.join(' '); });"
            + " nodes[n.type + ' ' + n.name] = {seen: n.visibleToAuthenticatedUsers, who: who}; });\n"
            + "var result = {answers: answers, nodes: nodes};")
    return javascript(code)


JAMIES = {"NutritionTarget Daily protein (Jamie)", "QuantitySpecification Daily protein (Jamie) range",
          "ExclusionConstraint No peanuts (Jamie)", "RecipeIdentity Daily supplements", "Plan Daily supplements v1",
          "Step Daily supplements v1 step 1", "Specification Daily supplements v1 step 1 eggs",
          "QuantitySpecification Daily supplements eggs quantity"}
HOUSEHOLDS = {"NutritionTarget Weekly fibre", "QuantitySpecification Weekly fibre range",
              "MealPlan Week of 2026-11-23", "TemporalRegion the week", "MealPlanEntry Mon Dinner -- Stew v1",
              "TemporalRegion Mon dinner", "QuantitySpecification Mon dinner servings", "MealShare Mon Dinner -- Jamie",
              "QuantitySpecification Mon Jamie servings", "Process Purchase t1", "TemporalRegion Purchase t1 time",
              "Allocation Purchase t1 -- draw", "Measurement Purchase t1 -- draw amount",
              "PortionOfSubstance Purchase t1 -- Eggs", "ContainerObject Purchase t1 -- Eggs container",
              "Quality Purchase t1 -- Eggs mass Quality", "Measurement Purchase t1 -- Eggs mass bought",
              "Measurement Purchase t1 -- Eggs mass assumed",
              "RecipeIdentity Stew", "Identifier Stew source", "Plan Stew v1", "QuantitySpecification Stew yield",
              "Step Stew v1 step 1", "Specification Stew v1 step 1 eggs", "QuantitySpecification Stew eggs quantity",
              "NutrientProfile Stew protein per serving", "DomainType Home prices", "DefaultSpecification Home prices -- Eggs",
              "QuantitySpecification Home prices -- Eggs price"}


@unittest.skipUnless(ENGINE, "needs node or gjs")
class WhoOwnsWhat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.done = run()

    def test_counted_by_hand(self):
        self.assertEqual((len(JAMIES), len(HOUSEHOLDS)), (8, 29))
        answer = self.done["answers"][0]
        self.assertEqual((answer["problem"], answer["changed"], answer["remaining"], answer["owned"]), (None, 37, 0, 37))

    def test_a_persons_own_is_theirs_and_the_household_reads_it(self):
        for name in JAMIES:
            self.assertEqual(self.done["nodes"][name], {"seen": False, "who": {"Jamie": "delete read write", "Home": "read"}}, name)

    def test_the_households_own_is_granted_to_it_alone(self):
        for name in HOUSEHOLDS:
            self.assertEqual(self.done["nodes"][name], {"seen": False, "who": {"Home": "delete read write"}}, name)

    def test_everything_else_stays_shared(self):
        rest = {k: v for k, v in self.done["nodes"].items() if k not in JAMIES | HOUSEHOLDS}
        self.assertIn("QuantitySpecification US prices (BLS) -- Eggs price", rest)    # a shared default's, though derived from
        self.assertIn("Plan Bruschetta v1", rest)
        for name, state in rest.items():
            self.assertEqual(state, {"seen": True, "who": {}}, name)

    def test_a_second_run_changes_nothing(self):
        twice = run(calls=2)["answers"]
        self.assertEqual([(a["changed"], a["remaining"]) for a in twice], [(37, 0), (0, 0)])

    def test_a_small_limit_takes_several_calls_and_ends_the_same(self):
        answers = run(calls=4, params={"limit": 10})
        self.assertEqual([(a["changed"], a["remaining"]) for a in answers["answers"]], [(10, 27), (10, 17), (10, 7), (7, 0)])
        self.assertEqual(answers["nodes"], self.done["nodes"])

    def test_check_changes_nothing_and_says_what_it_would(self):
        checked = run(params={"check": True})
        self.assertEqual((checked["answers"][0]["changed"], checked["answers"][0]["remaining"]), (0, 37))
        self.assertTrue(all(v == {"seen": True, "who": {}} for v in checked["nodes"].values()))

    def test_a_baseline_the_household_was_given_first_becomes_the_persons(self):
        """A baseline recipe loaded before the household linked it to Jamie was the household's; claimed again,
        the household keeps only reading it."""
        again = run(calls=2, extra="var was = jamie.hasBaseline.pop();\n", between="jamie.hasBaseline.push(was);")
        self.assertEqual(again["answers"][0]["changed"], 37)
        self.assertEqual(again["answers"][1]["changed"], 5)            # the recipe's five nodes, regranted
        self.assertEqual(again["nodes"]["Plan Daily supplements v1"],
                         {"seen": False, "who": {"Jamie": "delete read write", "Home": "read"}})

    def test_only_the_tools_account_may_run_it(self):
        self.assertIn("admin", run(me={"name": "Jamie", "type": "Person"})["answers"][0]["problem"])

    def test_an_instance_of_two_households_is_refused(self):
        refused = run(extra='node("Household", "Next door", {members: []});\n')["answers"][0]
        self.assertEqual(refused["problem"], "this instance has 2 households: ownership is worked out for one")


class WhatTheRepositoryKnows(unittest.TestCase):
    def test_the_public_recipes_are_the_files_in_data_recipes(self):
        names = ownership.shared_recipes(str(ROOT))
        self.assertEqual(len(names), len(list((ROOT / "data" / "recipes").glob("*.toml"))))
        self.assertIn("Bruschetta", names)

    def test_the_public_levels(self):
        self.assertEqual(ownership.PUBLIC_LEVELS, {"US prices 2017-18 adjusted (Purchase to Plate)", "US prices (BLS)",
                                                   "West prices (BLS)", "US supermarket"})

    def test_after_writing_does_nothing_without_a_household_and_with_several(self):
        class Rows:
            def __init__(self, n):
                self.n, self.posts = n, []

            def get(self, path, params=None):
                return {"result": [{"id": f"h{i}", "type": "Household", "name": f"h{i}"} for i in range(self.n)]}

            def post(self, path, payload):
                self.posts.append(path)
        for n, said in ((0, "no household"), (2, "2 households")):
            client = Rows(n)
            done = ownership.after_writing(client, str(ROOT))
            self.assertIn(said, done.note)
            self.assertEqual(client.posts, [])


if __name__ == "__main__":
    unittest.main()
