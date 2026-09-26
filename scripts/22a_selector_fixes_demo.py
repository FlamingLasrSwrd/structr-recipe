"""Verifies three fixes to the selector's inputs, all found by external
review, against throwaway fixtures built and removed by this script:

  A. StockPolicy resolution. Used to take the FIRST policy on the exact
     type (graph order decided behaviour), never looked at a policy on an
     ancestor, and never read includesSubtypes. Now: nearest level wins
     (like resolveDefault), a policy on an ancestor reaches a descendant
     only if includesSubtypes isn't False, and several policies on one
     type combine restrictively and order-independently. net_requirements
     accounts stock in pools per governing policy, honours
     includesSubtypes, and refuses a target it can't convert to grams.
  B. Exclusions. Used to ban the excluded type and foods linked DIRECTLY
     to it. Now transitive through both hierarchies: descendants of the
     excluded type, foods of any descendant origin, and those foods'
     descendants. A type ABOVE an excluded one stays allowed.
  C. Recipe outputs and inputs. Used to read only the FIRST output, and
     to treat an intermediate (made in step 1, consumed in step 2) as a
     raw ingredient. Now every FINAL output counts and intermediates are
     neither eaten nor required from stock.

Expected values are worked out here from raw quantities and profile
amounts, not by calling the functions under test. Everything created is
prefixed "TEST -- Z22 " and deleted in a finally block; an interrupted
earlier run is swept first.

Run with: python3 scripts/22a_selector_fixes_demo.py
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))

from structr_client import StructrClient
from mealplanner.material_accounting import candidate_input_requirements, candidate_outputs
from mealplanner.nutrition_scope import nutrient_profile_amount, serving_nutrient_amount
from mealplanner.fixtures import make_portion
from mealplanner.inventory import eligible_on_hand_with_urgency
from mealplanner.reservation import (
    Reserved, available_for_planning, combine_policy_fields, net_requirements, resolve_stock_policy,
)

_spec = importlib.util.spec_from_file_location("selector_11c", os.path.join(SCRIPTS_DIR, "11c_simple_selector.py"))
_selector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_selector)
excluded_domain_type_ids = _selector.excluded_domain_type_ids
candidate_consumed_types = _selector.candidate_consumed_types
candidate_optional_types = _selector.candidate_optional_types

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- Z22 "
FMT = "%Y-%m-%dT%H:%M:%S+0000"

# Parents before children; deleted in reverse.
DOMAIN_NAMES = [
    "Legume", "Lentils", "Red Lentils", "Chickpeas", "Grain", "Oats",
    "Pistachio Origin", "Pistachios", "Roasted Pistachios", "Plain Seed",
    "Flour", "Bread Flour",
]
SWEEP_ORDER = [
    "MealPlanEntry", "TemporalRegion", "Measurement", "Quality", "PortionOfSubstance", "Specification",
    "Step", "Plan", "QuantitySpecification", "RecipeIdentity", "StockPolicy", "ExclusionConstraint", "MealPlan",
]


def sweep(client):
    for type_name in SWEEP_ORDER:
        for node in client.get_all(type_name)["result"]:
            if node["name"].startswith(P):
                client.delete(f"/structr/rest/{type_name}/{node['id']}")
    for name in reversed(DOMAIN_NAMES):
        for node in client.get("/structr/rest/DomainType", params={"name": P + name})["result"]:
            client.delete(f"/structr/rest/DomainType/{node['id']}")


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def dt(name):
        return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]

    def hierarchy(name):
        return client.get("/structr/rest/TypeHierarchy", params={"name": name})["result"][0]["id"]

    types = {}

    def make_type(short, hier, parent=None, origins=None):
        fields = {"hierarchy": hierarchy(hier), "isLookupBearing": True}
        if parent:
            fields["parent"] = parent
        if origins:
            fields["hasBiologicalOrigin"] = origins
        types[short] = client.upsert("DomainType", "name", P + short, fields)
        return types[short]

    def qty(name, value, unit="g"):
        return client.upsert("QuantitySpecification", "name", P + name,
                             {"value": value, "unit": unit, "status": "specified"})

    def policy(name, applies_to, *, target=None, includes=True, storage=None, opened=None, sealed=None):
        fields = {"appliesTo": applies_to, "includesSubtypes": includes, "strictness": "soft", "weight": 0.1}
        if target is not None:
            fields["hasTargetLevel"] = qty(f"{name} target", target)
        if storage:
            fields["eligibleStorageConditions"] = [dt(s) for s in storage]
        if opened is not None:
            fields["eligibleWhenOpened"] = opened
        if sealed is not None:
            fields["eligibleWhenSealed"] = sealed
        return client.upsert("StockPolicy", "name", P + name, fields)

    def build_plan(name, servings, steps):
        recipe = client.upsert("RecipeIdentity", "name", P + name + " recipe", {"isRetired": False})
        plan = client.upsert("Plan", "name", P + name, {
            "specializationOf": recipe, "hasRecipeYield": qty(name + " yield", servings, "servings"),
        })
        for i, step in enumerate(steps, 1):
            step_id = client.upsert("Step", "name", f"{P}{name} step {i}", {"plan": plan, "instanceOf": dt("Braising")})
            for role, listing in (("input", step["in"]), ("output", step["out"])):
                for type_name, grams in listing:
                    client.upsert("Specification", "name", f"{P}{name} s{i} {role} {type_name}", {
                        "step": step_id, "hasParticipationRole": role, "specifies": dt(type_name),
                        "hasSpecifiedQuantity": qty(f"{name} s{i} {role} {type_name} qty", grams), "isOptional": False,
                    })
            for type_name, grams in step.get("optional", []):
                client.upsert("Specification", "name", f"{P}{name} s{i} optional {type_name}", {
                    "step": step_id, "hasParticipationRole": "input", "specifies": dt(type_name),
                    "hasSpecifiedQuantity": qty(f"{name} s{i} optional {type_name} qty", grams), "isOptional": True,
                })
            for type_name in step.get("instruments", []):    # instruments carry no quantity (invariant 6)
                client.upsert("Specification", "name", f"{P}{name} s{i} instrument {type_name}", {
                    "step": step_id, "hasParticipationRole": "instrument", "specifies": dt(type_name), "isOptional": False,
                })
        return client.get_all("Plan", plan)["result"]

    sweep(client)
    try:
        # ---------------------------------------------------------------- A
        print("[A1] combine_policy_fields is restrictive and order-independent (pure)...")
        one = {"eligibleWhenOpened": None, "eligibleWhenSealed": True, "storage": {"Fridge"}, "includesSubtypes": True}
        two = {"eligibleWhenOpened": False, "eligibleWhenSealed": None, "storage": {"Fridge", "Pantry"}, "includesSubtypes": None}
        three = {"eligibleWhenOpened": None, "eligibleWhenSealed": None, "storage": {"Freezer"}, "includesSubtypes": False}
        ab, ba = combine_policy_fields([one, two]), combine_policy_fields([two, one])
        check(ab == ba, "same result whichever policy is listed first")
        check(ab["eligibleWhenOpened"] is False and ab["eligibleWhenSealed"] is True and ab["storage"] == {"Fridge"},
              "flags AND together (None = unstated); storage sets intersect")
        c = combine_policy_fields([one, three])
        check(c["storage"] == set() and c["includesSubtypes"] is False,
              "disjoint storage sets give an EMPTY set (nothing qualifies), and one False includesSubtypes wins")

        print("\n[A2] resolve_stock_policy against a real hierarchy...")
        legume = make_type("Legume", "Food Identity")
        lentils = make_type("Lentils", "Food Identity", legume)
        red = make_type("Red Lentils", "Food Identity", lentils)
        chick = make_type("Chickpeas", "Food Identity", legume)
        p1 = P + "policy P1 legume"
        p2 = P + "policy P2 legume exact-only"
        p3 = P + "policy P3 lentils"
        p4 = P + "policy P4 lentils"
        policy("policy P1 legume", legume, target=500, includes=True, storage=["Pantry"])
        policy("policy P2 legume exact-only", legume, target=900, includes=False)
        policy("policy P3 lentils", lentils, target=200, includes=True, storage=["Fridge"])
        policy("policy P4 lentils", lentils, includes=True, storage=["Fridge", "Pantry"], opened=False)

        r = resolve_stock_policy(client, red)
        check(r is not None and r.policy_names == [p3, p4] and r.tied and r.distance == 1,
              "Red Lentils: nearest level (Lentils) wins over Legume; two policies tie")
        check(r.storage_conditions == {"Fridge"} and r.eligible_when_opened is False and r.include_subtypes,
              "tied policies combined: storage {Fridge} intersect {Fridge, Pantry}, not eligible when opened")
        r = resolve_stock_policy(client, lentils)
        check(r.distance == 0 and r.policy_names == [p3, p4], "Lentils: its own policies, distance 0")
        r = resolve_stock_policy(client, legume)
        check(r.policy_names == [p1, p2] and r.tied and r.storage_conditions == {"Pantry"} and r.include_subtypes is False,
              "Legume: both its own policies apply; exact-only one makes the combined pool exact-only")
        r = resolve_stock_policy(client, chick)
        check(r.policy_names == [p1] and not r.tied and r.distance == 1 and r.include_subtypes,
              "Chickpeas: inherits P1 from Legume, but NOT P2 (includesSubtypes False doesn't reach descendants)")
        check(resolve_stock_policy(client, make_type("Grain", "Food Identity")) is None, "a type with no policy anywhere resolves to None")

        print("\n[A3] net_requirements: pools, includesSubtypes, unit-checked targets...")
        oats = make_type("Oats", "Food Identity", types["Grain"])
        portion = client.upsert("PortionOfSubstance", "name", P + "oats portion", {"instanceOf": oats})
        quality = client.upsert("Quality", "name", P + "oats mass", {"hasKind": dt("Mass"), "inheresIn": portion})
        client.upsert("Measurement", "name", P + "oats mass obs", {
            "value": 400.0, "unit": "g", "status": "observed",
            "hasTime": (now - timedelta(hours=1)).strftime(FMT), "isAboutQuality": quality})
        grain_policy = policy("policy grain", types["Grain"], target=600, includes=True)
        oats_plan = build_plan("oats plan", 2.0, [{"in": [], "out": []}])
        step_id = oats_plan["steps"][0]["id"]
        client.upsert("Specification", "name", P + "oats plan input oats", {
            "step": step_id, "hasParticipationRole": "input", "specifies": oats,
            "hasSpecifiedQuantity": qty("oats input qty", 250), "isOptional": False})
        meal_plan = client.upsert("MealPlan", "name", P + "week", {})
        region = client.upsert("TemporalRegion", "name", P + "window", {
            "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(hours=1)).strftime(FMT)})
        client.upsert("MealPlanEntry", "name", P + "oats entry", {
            "memberOf": meal_plan, "isAbout": region, "references": oats_plan["id"],
            "hasPlannedServings": 2.0, "isSkipped": False})

        net = net_requirements(client, meal_plan, now)
        check(abs(net.get(types["Grain"], -1) - (250 + 600 - 400)) < 0.01 and oats not in net,
              f"includesSubtypes True: oats demand and Grain's target share ONE pool -> 250 + 600 - 400 = 450 (got {net.get(types['Grain'])})")
        client.patch(f"/structr/rest/StockPolicy/{grain_policy}", {"includesSubtypes": False})
        net = net_requirements(client, meal_plan, now)
        check(abs(net.get(types["Grain"], -1) - 600) < 0.01 and oats not in net,
              f"includesSubtypes False: policy no longer reaches Oats and its pool holds none of Oats' stock -> 600 - 0 = 600 (got {net.get(types['Grain'])})")
        client.patch(f"/structr/rest/StockPolicy/{grain_policy}", {"includesSubtypes": True, "hasTargetLevel": qty("bad target", 3, "bushel")})
        try:
            net_requirements(client, meal_plan, now)
            check(False, "a target in an unconvertible unit raises")
        except ValueError as exc:
            check("doesn't convert to grams" in str(exc), "a target in an unconvertible unit raises instead of being dropped")
        client.delete(f"/structr/rest/StockPolicy/{grain_policy}")   # deliberately broken above; later checks call net_requirements again

        print("\n[A4] Nested policies: the NEAREST policy owns the physical stock...")
        flour = make_type("Flour", "Food Identity")
        bread = make_type("Bread Flour", "Food Identity", flour)
        policy("policy flour", flour, target=2000, includes=True)
        policy("policy bread flour", bread, target=1000, includes=True)
        make_portion(client, P + "bread flour portion", P + "Bread Flour", 2000.0, age_days=0, now=now, perishability=None)
        net = net_requirements(client, meal_plan, now)
        # 2 kg of bread flour meets bread flour's own 1 kg target with room to spare, but it belongs to that
        # pool, so "keep 2 kg of flour" still needs the whole 2 kg (it used to read 0: the same flour counted twice)
        check(abs(net.get(flour, -1) - 2000.0) < 0.01 and bread not in net,
              f"flour pool needs its full 2000 g, and bread flour needs nothing (got flour={net.get(flour)}, bread={net.get(bread)})")

        print("\n[A5] Availability across the type tree, against real stock and real reservations...")
        make_portion(client, P + "lentils portion", P + "Lentils", 500.0, age_days=0, now=now, perishability=None)
        make_portion(client, P + "chickpeas portion", P + "Chickpeas", 500.0, age_days=0, now=now, perishability=None)
        stock = lambda t: eligible_on_hand_with_urgency(client, types[t], now)[0]
        legume_stock, chick_stock = stock("Legume"), stock("Chickpeas")
        check(abs(legume_stock - 1000.0) < 0.01 and abs(chick_stock - 500.0) < 0.01,
              f"fixture stock: 1000 g of legumes, 500 g of them chickpeas (got {legume_stock:g} and {chick_stock:g})")
        by_lentils = Reserved.from_by_type(client, {types["Lentils"]: 500.0})
        got = available_for_planning(client, types["Legume"], legume_stock, now, by_lentils)
        check(abs(got - 500.0) < 0.01,
              f"a generic Legume demand sees the 500 g reserved for lentils: 1000 - 500 = 500 (got {got:g})")
        generic = Reserved.from_by_type(client, {types["Legume"]: 600.0})
        got = available_for_planning(client, types["Chickpeas"], chick_stock, now, generic)
        check(abs(got - 400.0) < 0.01,
              f"a chickpea demand sees the shared pool tightened by a generic 600 g claim: 1000 - 600 = 400 (got {got:g})")
        got = available_for_planning(client, types["Chickpeas"], chick_stock, now, by_lentils)
        check(abs(got - 500.0) < 0.01, f"a lentil reservation leaves the chickpeas' own 500 g free (got {got:g})")

        # ---------------------------------------------------------------- B
        print("\n[B] Exclusions are transitive...")
        tree_nut = dt("Tree Nut")
        origin = make_type("Pistachio Origin", "Biological Origin", tree_nut)
        pistachios = make_type("Pistachios", "Food Identity", None, [origin])
        roasted = make_type("Roasted Pistachios", "Food Identity", pistachios)
        seed = make_type("Plain Seed", "Food Identity")

        def banned_by(target_id, label):
            constraint = client.upsert("ExclusionConstraint", "name", P + "exclude " + label,
                                       {"appliesTo": target_id, "strictness": "hard"})
            try:
                return excluded_domain_type_ids(client)
            finally:
                client.delete(f"/structr/rest/ExclusionConstraint/{constraint}")

        banned = banned_by(tree_nut, "tree nut")
        check(origin in banned, "excluding Tree Nut bans its sub-origin")
        check(pistachios in banned, "...and a food whose origin is that SUB-origin (one level below)")
        check(roasted in banned, "...and that food's own subtype")
        check(seed not in banned, "...but not an unrelated food")
        banned = banned_by(legume, "legume")
        check({lentils, red, chick} <= banned and types["Grain"] not in banned and oats not in banned,
              "excluding a food type bans all its descendants and nothing else")
        banned = banned_by(red, "red lentils")
        check(red in banned and lentils not in banned and legume not in banned,
              "excluding a subtype does NOT ban the types above it")

        print("\n[B2] Which Specifications count as ingredients for an exclusion (real Specifications)...")
        roles = build_plan("roles", 2.0, [{
            "in": [(P + "Plain Seed", 100)], "out": [(P + "Grain", 100)],
            "optional": [(P + "Roasted Pistachios", 20)], "instruments": [P + "Chickpeas"]}])
        consumed = candidate_consumed_types(client, roles)
        check(consumed == {types["Plain Seed"], types["Grain"]},
              "a required input and the output count; an optional input and an instrument do not")
        check(candidate_optional_types(client, roles) == {types["Roasted Pistachios"]},
              "the optional input is reported separately, so the user can be told to leave it out")

        # ---------------------------------------------------------------- C
        print("\n[C] Every final output counts; intermediates are neither eaten nor stocked...")
        protein = dt("Protein")
        amount = {n: nutrient_profile_amount(client, dt(n), protein)
                  for n in ("Chicken Breast (braised)", "Beef and Broccoli Stir-Fry", "Buttered Pasta with Parmesan", "Butter")}
        chain = build_plan("chain", 3.0, [
            {"in": [("Chicken Breast (raw)", 500)], "out": [("Chicken Breast (braised)", 375)]},
            {"in": [("Chicken Breast (braised)", 375), ("Butter", 30)], "out": [("Buttered Pasta with Parmesan", 405)]},
        ])
        outs = candidate_outputs(client, chain)
        check([(client.get_all("DomainType", t)["result"]["name"], g) for t, g in outs] == [("Buttered Pasta with Parmesan", 405.0)],
              "two-step chain: only the final output counts (the braised chicken is an intermediate)")
        got = serving_nutrient_amount(client, chain, protein)
        want = 405 * amount["Buttered Pasta with Parmesan"] / 100 / 3
        check(got is not None and abs(got - want) < 0.01, f"...so protein per serving is {want:.2f} g, not the intermediate's (got {got})")
        reqs = {client.get_all("DomainType", t)["result"]["name"]: g for t, g in candidate_input_requirements(client, chain)}
        check(reqs == {"Chicken Breast (raw)": 500.0, "Butter": 30.0},
              f"raw requirements exclude the intermediate braised chicken (got {reqs})")

        two_out = build_plan("two outputs", 2.0, [{
            "in": [("Chicken Breast (raw)", 400)],
            "out": [("Chicken Breast (braised)", 300), ("Beef and Broccoli Stir-Fry", 200)]}])
        got = serving_nutrient_amount(client, two_out, protein)
        want = (300 * amount["Chicken Breast (braised)"] + 200 * amount["Beef and Broccoli Stir-Fry"]) / 100 / 2
        check(got is not None and abs(got - want) < 0.01, f"one step, two outputs: BOTH count -> {want:.2f} g per serving (got {got})")

        if amount["Butter"] is None:
            byproduct = build_plan("unknown byproduct", 2.0, [{
                "in": [("Chicken Breast (raw)", 400)],
                "out": [("Chicken Breast (braised)", 300), ("Butter", 50)]}])
            check(serving_nutrient_amount(client, byproduct, protein) is None,
                  "an output with no profile makes the recipe's nutrition UNKNOWN, not a partial sum")
    finally:
        sweep(client)
        print("\n[cleanup] all Z22 fixtures removed")

    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
