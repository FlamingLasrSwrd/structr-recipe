"""Checks, against real Structr, the fixes made for the open items the
second external review left:

  A. Chained recipes. expected_combination_output() used to sum every input of
     every Step, so a Plan whose Step 2 consumed Step 1's output counted that
     material twice. It now routes material through the Steps.
  B. Expiry. Shelf life used to run from the LATEST weighing, so reweighing
     restarted the clock. It now runs from the Process the food began to exist
     in (a purchase), else the EARLIEST weighing.
  C. Reservation scaling. planned servings / recipe yield used to treat a
     missing yield as 1; it now refuses.
  D. Variety. A recipe planned for next week used to count as "just used", and
     a skipped entry counted as a use.
  E. structr_client: get_all() reads every page of a collection, and a
     ReadCache gives the same answers as reading directly.

Expected values are worked out here from the seed constants (yield factors,
shelf lives) and the quantities below, not by calling the functions under
test. Everything created is prefixed "TEST -- Z25 " and deleted in a finally
block; an interrupted earlier run is swept first.

Run with: python3 scripts/25a_open_pieces_demo.py
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))

from structr_client import ReadCache
from mealplanner.connection import connect
from mealplanner.fixtures import make_portion
from mealplanner.inventory import eligible_on_hand_with_urgency, instance_expiration
from mealplanner.material_accounting import expected_combination_output
from mealplanner.reservation import committed_requirements
from mealplanner.seed_vocabulary import FRESH_MEAT_SHELF_LIFE, REALISTIC_YIELD_DEFAULTS, YIELD_DEFAULT
from mealplanner.unit_conversion import QuantityError

_spec = importlib.util.spec_from_file_location("selector_11c", os.path.join(SCRIPTS_DIR, "11c_simple_selector.py"))
_selector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_selector)
variety_score = _selector.variety_score

P = "TEST -- Z25 "
FMT = "%Y-%m-%dT%H:%M:%S+0000"

SWEEP_ORDER = [
    "MealPlanEntry", "MealPlan", "Process", "TemporalRegion", "Measurement", "Quality", "PortionOfSubstance",
    "Specification", "Step", "Plan", "QuantitySpecification", "RecipeIdentity",
]


def sweep(client):
    for type_name in SWEEP_ORDER:
        for node in client.get_all(type_name)["result"]:
            if node["name"].startswith(P):
                client.delete(f"/structr/rest/{type_name}/{node['id']}")


def main():
    client = connect()
    client.wait_until_ready()
    now = datetime.now(timezone.utc)
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def dt(name):
        return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]

    def qty(name, value, unit="g"):
        return client.upsert("QuantitySpecification", "name", P + name, {"value": value, "unit": unit, "status": "specified"})

    def region(name, when):
        return client.upsert("TemporalRegion", "name", P + name, {"hasBeginning": when.strftime(FMT)})

    def build_plan(name, servings, steps):
        """steps: [(transformation, [(type, grams or None)], [output type])]"""
        fields = {"specializationOf": client.upsert("RecipeIdentity", "name", P + name + " recipe", {"isRetired": False})}
        if servings is not None:
            fields["hasRecipeYield"] = qty(name + " yield", servings, "servings")
        plan = client.upsert("Plan", "name", P + name, fields)
        for i, (transformation, inputs, outputs) in enumerate(steps, 1):
            step = client.upsert("Step", "name", f"{P}{name} step {i}", {"plan": plan, "instanceOf": dt(transformation)})
            for type_name, grams in inputs:
                spec = {"step": step, "hasParticipationRole": "input", "specifies": dt(type_name), "isOptional": False}
                if grams is not None:
                    spec["hasSpecifiedQuantity"] = qty(f"{name} s{i} in {type_name}", grams)
                client.upsert("Specification", "name", f"{P}{name} s{i} input {type_name}", spec)
            for type_name in outputs:
                client.upsert("Specification", "name", f"{P}{name} s{i} output {type_name}", {
                    "step": step, "hasParticipationRole": "output", "specifies": dt(type_name), "isOptional": False,
                })
        return plan

    def entry(name, meal_plan, plan, when, servings=None, skipped=False):
        fields = {"memberOf": meal_plan, "isAbout": region(name + " region", when), "isSkipped": skipped}
        if plan:
            fields["references"] = plan
        if servings is not None:
            fields["hasPlannedServings"] = servings
        return client.upsert("MealPlanEntry", "name", P + name, fields)

    sweep(client)
    try:
        # ---------------------------------------------------------------- A
        print("[A] Chained recipe: braise chicken, then stir-fry the braised chicken with broccoli...")
        braise = YIELD_DEFAULT["value"]["value"]                                  # chicken, braised: 0.75
        broccoli = next(f for t, k, _, f in REALISTIC_YIELD_DEFAULTS if (t, k) == ("Broccoli", "Stir-Frying"))   # 0.9
        # 400 g chicken x 0.75 = 300 g braised; that goes into step 2 (no yield of its own: conserved);
        # 100 g broccoli x 0.9 = 90 g. The dish is 300 + 90 = 390 g, however the recipe is written.
        want = 400.0 * braise + 100.0 * broccoli
        for label, stated in (("amount of the braised chicken left to be worked out", None),
                              ("braised chicken stated as 300 g", 300.0)):
            plan = build_plan("chain amountless" if stated is None else "chain stated", 4.0, [
                ("Braising", [("Chicken Breast (raw)", 400.0)], ["Chicken Breast (braised)"]),
                ("Stir-Frying", [("Chicken Breast (braised)", stated), ("Broccoli", 100.0)], ["Beef and Broccoli Stir-Fry"]),
            ])
            got = expected_combination_output(client, client.get_all("Plan", plan)["result"])
            check(abs(got - want) < 1e-6,
                  f"{label}: {want:g} g (engine: {got:g}; summing every input would give "
                  f"{400 * braise + (stated or 0) + 100 * broccoli:g})")

        # ---------------------------------------------------------------- B
        print("\n[B] Expiry runs from purchase, else the earliest weighing (Fresh Meat, fridge, sealed)...")
        shelf = next(d for storage, opened, d in FRESH_MEAT_SHELF_LIFE if (storage, opened) == ("Fridge", "Sealed"))   # 5 days
        reweighed = make_portion(client, P + "reweighed chicken", "Chicken Breast (raw)", 400.0, age_days=1, now=now)
        quality = next(q for q in client.get_all("PortionOfSubstance", reweighed)["result"]["bearerOf"] if q["type"] == "Quality")
        client.post("/structr/rest/Measurement", {
            "name": P + "reweighed chicken second weighing", "value": 380.0, "unit": "g", "status": "observed",
            "hasTime": now.strftime(FMT), "isAboutQuality": quality["id"], "visibleToAuthenticatedUsers": True,
        })
        expired, left = instance_expiration(client, client.get_all("PortionOfSubstance", reweighed)["result"], now)
        want = shelf - 1.0          # first weighed a day ago; the weighing just now does not restart it
        check(left is not None and abs(left - want) < 0.01 and not expired,
              f"first weighed 1 day ago and weighed again now: {want:g} days left, not {shelf:g} (engine: {left})")

        bought = make_portion(client, P + "old purchase chicken", "Chicken Breast (raw)", 400.0, age_days=1, now=now)
        purchase = client.upsert("Process", "name", P + "purchase 6 days ago", {
            "occupiesTemporalRegion": region("purchase region", now - timedelta(days=6))})
        client.patch(f"/structr/rest/PortionOfSubstance/{bought}", {"beginsToExistDuring": purchase})
        expired, left = instance_expiration(client, client.get_all("PortionOfSubstance", bought)["result"], now)
        want = shelf - 6.0          # bought 6 days ago, first weighed at home yesterday
        check(left is not None and abs(left - want) < 0.01 and expired,
              f"bought 6 days ago, weighed 1 day ago: {want:g} days left, expired (engine: {left})")

        # ---------------------------------------------------------------- C
        print("\n[C] Reservation scales by planned servings / recipe yield, and refuses an unstated yield...")
        week = client.upsert("MealPlan", "name", P + "week", {"timeBudgetMinutes": 60.0})
        recipe = build_plan("roast for four", 4.0, [("Braising", [("Chicken Breast (raw)", 400.0)], ["Chicken Breast (braised)"])])
        entry("two servings of the roast", week, recipe, now + timedelta(days=1), servings=2.0)
        committed = committed_requirements(client, week)
        chicken = dt("Chicken Breast (raw)")
        check(committed.get(chicken) == 400.0 * 2.0 / 4.0,
              f"2 servings of a recipe for 4 that uses 400 g chicken reserves 200 g (engine: {committed.get(chicken)})")

        unstated = build_plan("roast with no yield", None, [("Braising", [("Chicken Breast (raw)", 400.0)], ["Chicken Breast (braised)"])])
        entry("two servings of the unstated roast", week, unstated, now + timedelta(days=2), servings=2.0)
        try:
            committed_requirements(client, week)
            check(False, "an entry for a recipe with no yield raises QuantityError (it was accepted)")
        except QuantityError as problem:
            check("two servings of the unstated roast" in str(problem),
                  f"an entry for a recipe with no yield raises QuantityError naming the entry ({problem})")

        # ---------------------------------------------------------------- D
        print("\n[D] Variety: distance to the nearest use, past or planned; skipped entries don't count...")
        used = build_plan("variety recipe", 4.0, [("Braising", [("Chicken Breast (raw)", 100.0)], ["Chicken Breast (braised)"])])
        entry("variety planned next week", week, used, now + timedelta(days=7), servings=1.0)
        check(abs(variety_score(client, used, now) - 0.5) < 1e-3,
              f"planned 7 days ahead of a 14-day cap scores 0.5, as one eaten 7 days ago would (engine: {variety_score(client, used, now):.4f})")
        entry("variety skipped yesterday", week, used, now - timedelta(days=1), servings=1.0, skipped=True)
        check(abs(variety_score(client, used, now) - 0.5) < 1e-3, "a skipped entry yesterday changes nothing")
        only_skipped = build_plan("skipped only recipe", 4.0, [("Braising", [("Chicken Breast (raw)", 100.0)], ["Chicken Breast (braised)"])])
        entry("only skipped", week, only_skipped, now - timedelta(days=1), servings=1.0, skipped=True)
        check(variety_score(client, only_skipped, now) == 1.0, "a recipe whose only entry was skipped counts as never used")

        # ---------------------------------------------------------------- E
        print("\n[E] Reads: every page comes back, and the cache changes no answer...")
        every = client.get_all("DomainType")
        small_pages = client.get_all("DomainType", page_size=7)
        check(len(every["result"]) >= 45 and {r["id"] for r in small_pages["result"]} == {r["id"] for r in every["result"]}
              and len(small_pages["result"]) == len(every["result"]),
              f"DomainType read in pages of 7 returns all {len(every['result'])} rows, each once")
        cbr = dt("Chicken Breast (raw)")
        direct = eligible_on_hand_with_urgency(client, cbr, now)
        cached = eligible_on_hand_with_urgency(ReadCache(client), cbr, now)
        check(direct == cached, f"eligible stock and soonest expiry are identical through a ReadCache ({direct})")
    finally:
        sweep(client)
        print("\n(fixtures removed)")

    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for label in failures:
            print(f"  - {label}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
