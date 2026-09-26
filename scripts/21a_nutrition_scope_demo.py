"""Demonstrates mealplanner/nutrition_scope.py against real recipes: a
NutritionTarget is judged at the scope it declares, not against one
meal in isolation. Fixes a correctness finding from external review.

Scenario, in one MealPlan with a HARD daily protein range of 50-80 g:
  Mon   pasta (lunch)                       -> 1 meal planned
  Tue   pasta (lunch) + chicken (dinner)    -> lands inside the range
  Wed   stir-fry (lunch) + stir-fry (dinner)-> blows through the ceiling
Then the selector is asked what to cook for Monday dinner and for
Thursday dinner (nothing planned Thursday). The old per-meal comparison
would have judged every candidate identically on both days.

Checks compare the selector's and report's verdicts with arithmetic done
here from per-serving amounts alone, so they test the day grouping and
aggregation rather than restating them.

Self-cleaning: creates its entries and temporal regions, deletes them in
a finally block, and removes leftovers from an interrupted earlier run
first. An earlier demo (20a) left an entry behind, which silently
changed other scripts' variety scores; this one leaves the MealPlan and
its target only, neither of which any other script reads.

Run with: python3 scripts/21a_nutrition_scope_demo.py
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))

from structr_client import StructrClient
from mealplanner.nutrition_scope import nutrition_report, serving_nutrient_amount

_spec = importlib.util.spec_from_file_location("selector_11c", os.path.join(SCRIPTS_DIR, "11c_simple_selector.py"))
_selector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_selector)
select = _selector.select

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- NutriScope "
FMT = "%Y-%m-%dT%H:%M:%S+0000"
MONDAY = datetime(2026, 9, 28, tzinfo=timezone.utc)
CEILING, FLOOR = 80.0, 50.0


def cleanup(client):
    for type_name in ("MealPlanEntry", "TemporalRegion"):
        for node in client.get_all(type_name)["result"]:
            if node["name"].startswith(P):
                client.delete(f"/structr/rest/{type_name}/{node['id']}")


def add_entry(client, meal_plan_id, plan_id, day_offset, hour, label, servings):
    start = MONDAY + timedelta(days=day_offset, hours=hour)
    region = client.upsert("TemporalRegion", "name", f"{P}window {label}", {
        "hasBeginning": start.strftime(FMT), "hasEnd": (start + timedelta(hours=1)).strftime(FMT),
    })
    return client.upsert("MealPlanEntry", "name", f"{P}{label}", {
        "memberOf": meal_plan_id, "isAbout": region, "references": plan_id,
        "hasPlannedServings": servings, "isSkipped": False,
    })


def plan_id(client, short):
    return client.get("/structr/rest/Plan", params={"name": f"TEST -- {short} v1"})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)
    all_ok = True

    def check(ok, label):
        nonlocal all_ok
        all_ok &= ok
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    cleanup(client)
    protein = client.get("/structr/rest/DomainType", params={"name": "Protein"})["result"][0]["id"]
    pasta, chicken, stirfry = (plan_id(client, n) for n in
                               ("Buttered Pasta with Parmesan", "Braised Chicken Breast", "Beef and Broccoli Stir-Fry"))

    print("[1] MealPlan with a HARD daily protein range 50-80 g...")
    rng = client.upsert("QuantitySpecification", "name", "TEST -- NutriScope daily protein range 50 to 80g", {
        "minValue": FLOOR, "maxValue": CEILING, "unit": "g", "status": "specified"})
    target = client.upsert("NutritionTarget", "name", "TEST -- NutriScope hard daily protein range", {
        "forNutrient": protein, "hasTargetRange": rng, "hasTimeScope": "daily",
        "dayBoundaryRule": "midnight", "strictness": "hard"})
    meal_plan = client.upsert("MealPlan", "name", "TEST -- Nutrition scope demo week", {
        "timeBudgetMinutes": 60.0, "timeBudgetWeight": 0.5, "varietyWeight": 0.5})
    client.patch(f"/structr/rest/MealPlan/{meal_plan}", {"hasConstraint": [target]})

    per = {name: serving_nutrient_amount(client, client.get_all("Plan", pid)["result"], protein)
           for name, pid in (("pasta", pasta), ("chicken", chicken), ("stir-fry", stirfry))}
    print("    protein per serving: " + ", ".join(f"{k}={v:.1f}g" for k, v in per.items()))

    try:
        print("\n[2] Planning Mon-Wed...")
        add_entry(client, meal_plan, pasta, 0, 12, "Mon lunch pasta", 4.0)
        add_entry(client, meal_plan, pasta, 1, 12, "Tue lunch pasta", 4.0)
        add_entry(client, meal_plan, chicken, 1, 18, "Tue dinner chicken", 2.0)
        add_entry(client, meal_plan, stirfry, 2, 12, "Wed lunch stir-fry", 2.0)
        add_entry(client, meal_plan, stirfry, 2, 18, "Wed dinner stir-fry", 2.0)

        print("\n[3] Selector for Monday dinner (pasta already eaten that day)...")
        mon_dinner = MONDAY + timedelta(hours=18)
        by_name = {"pasta": "Buttered Pasta", "chicken": "Braised Chicken", "stir-fry": "Beef and Broccoli"}
        ranked = select(client, meal_plan, now, slot_start=mon_dinner)
        for r in ranked:
            print(f"    {'DISQUALIFIED' if r['disqualified'] else 'score=%.3f' % r['score']:13s} {r['plan']['name']:42s} {r['reason'][:110]}")
        for key, frag in by_name.items():
            got = next(r for r in ranked if frag in r["plan"]["name"])
            expect_disq = per["pasta"] + per[key] > CEILING
            check(got["disqualified"] == expect_disq,
                  f"Mon dinner {key}: planned {per['pasta']:.1f} + {per[key]:.1f} = {per['pasta'] + per[key]:.1f}g "
                  f"-> {'disqualified' if expect_disq else 'allowed'}")

        print("\n[4] Selector for Thursday dinner (nothing else planned that day)...")
        ranked = select(client, meal_plan, now, slot_start=MONDAY + timedelta(days=3, hours=18))
        for key, frag in by_name.items():
            got = next(r for r in ranked if frag in r["plan"]["name"])
            check(got["disqualified"] == (per[key] > CEILING),
                  f"Thu dinner {key}: {per[key]:.1f}g alone -> {'disqualified' if per[key] > CEILING else 'allowed'}")
        print(f"    (the old per-meal comparison judged every candidate as if it were alone, "
              f"so Monday would have looked identical to Thursday)")

        print("\n[5] Selector with no slot: a daily target must be skipped and said so, not guessed...")
        ranked = select(client, meal_plan, now)
        got = next(r for r in ranked if "Buttered Pasta" in r["plan"]["name"])
        check("daily target not scored" in got["reason"], "reason names the skipped daily target")

        print("\n[6] nutrition_report(): where the hard MINIMUM is actually judged...")
        rows = {r["group"]: r for r in nutrition_report(client, meal_plan)}
        expected = {
            "2026-09-28": per["pasta"],
            "2026-09-29": per["pasta"] + per["chicken"],
            "2026-09-30": 2 * per["stir-fry"],
        }
        for day, total in expected.items():
            want = "above_max" if total > CEILING else "below_min" if total < FLOOR else "ok"
            row = rows.get(day, {})
            print(f"    {day}: total={row.get('total', float('nan')):.1f}g status={row.get('status')} (expected {want})")
            check(row.get("status") == want and abs(row.get("total", -1) - total) < 0.01, f"{day} total and status")
        check("2026-10-01" not in rows, "a day with nothing planned isn't reported")
    finally:
        cleanup(client)
        print("\n[cleanup] entries and temporal regions removed")

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed. Nutrition targets are judged at their declared scope.")


if __name__ == "__main__":
    main()
