"""The planner against real Structr: a hard nutritional minimum that the
per-slot selector cannot meet (docs/optimizer-design.md Sec 2), met.

Fixtures: five recipes with one serving of 100 g each, so a recipe's protein per
serving is just its NutrientProfile amount (12, 10, 24, 30, 45 g), taking 20, 25,
35, 40 and 90 minutes; a MealPlan with a HARD daily protein range of 70-140 g, a
30-minute time budget and weight 0.6 on time fit (no variety, stock or waste
weight). The profiles are marked `sourced`: they are throwaway TEST fixtures, and
a planner will not decide a hard target on placeholder data.

Expected values are worked out here with plain arithmetic and an enumeration of
every menu, not by calling the planner. The end-to-end proof that a committed
plan meets the minimum uses nutrition_report(), which predates the planner and
shares no code with it.

  1  Only the five fixtures are eligible under the hard target (every recipe with
     placeholder or missing nutrition is refused, and the reason says so).
  2  Three slots on one day: the planner finds the best feasible menu; exact,
     beam and an independent enumeration agree on its score.
  3  Committing it writes MealPlanEntries the model's validators accept, and
     nutrition_report() judges the day "ok" at the expected total.
  4  Planning again with those entries in place treats them as fixed.
  5  A minimum no menu can reach gives a diagnosis with the exact shortfall, and
     writes nothing.
  6  A fixture whose figure is switched to placeholder is left out.
  7  An entry already in the plan counts towards the day.
  8  Cook once, eat twice: a leftover entry is accepted by the validators, and
     the keeping time comes from the live "Cooked Leftover" shelf-life default.

Everything created is prefixed "TEST -- Z26 " and deleted in a finally block; an
interrupted earlier run is swept first.

Run with: python3 scripts/26a_planner_demo.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.nutrition_scope import nutrition_report
from mealplanner.planning.evaluate import evaluate, ineligible_reason
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import Pick
from mealplanner.planning.plan import plan_week
from mealplanner.planning.commit import commit_plan
from mealplanner.planning.search import beam
from mealplanner.typetree import dt

P = "TEST -- Z26 "
FMT = "%Y-%m-%dT%H:%M:%S+0000"
BUDGET, W_TIME, W_TARGET = 30.0, 0.6, 0.2
FLOOR, CEILING = 70.0, 140.0
RECIPES = {                      # name: (protein g per serving, minutes)
    "buttered pasta": (12.0, 20.0), "veggie stir-fry": (10.0, 25.0), "omelette": (24.0, 35.0),
    "chicken salad": (30.0, 40.0), "braised chicken": (45.0, 90.0),
}
SWEEP_ORDER = [
    "MealPlanEntry", "MealPlan", "TemporalRegion", "NutritionTarget", "Specification", "Step", "Plan",
    "RecipeIdentity", "NutrientProfile", "QuantitySpecification", "DomainType",
]


def time_fit(minutes):
    """1 within the budget, then 1 - overage / budget, never below 0 (worked by hand, not imported)."""
    return 1.0 if minutes <= BUDGET else max(0.0, 1.0 - (minutes - BUDGET) / BUDGET)


def best_objective(names, slots, floor=FLOOR, leftovers=False, keep_days=3.0):
    """The best score over EVERY way of filling the slots, worked out with plain arithmetic.

    slots: chronological [(start in minutes, fixed recipe or None)]. An open slot cooks one of
    `names` (score W_TIME x its time fit) or, if `leftovers`, eats the leftovers of an earlier
    cook: allowed once that cook has finished and while the food keeps, scoring W_TIME x 1 (nothing
    to cook). A fixed slot adds its recipe's protein and no score of its own. The day's protein
    must lie in [floor, CEILING]; the target's weight is added once for a day that does."""
    best = [None]

    def rec(i, kinds, total, score):
        if i == len(slots):
            if floor <= total <= CEILING:
                value = score + W_TARGET
                best[0] = value if best[0] is None else max(best[0], value)
            return
        start, fixed = slots[i]
        if fixed:
            rec(i + 1, kinds + [("cook", fixed)], total + RECIPES[fixed][0], score)
            return
        for name in names:
            grams, minutes = RECIPES[name]
            rec(i + 1, kinds + [("cook", name)], total + grams, score + W_TIME * time_fit(minutes))
        if leftovers:
            for j in range(i):
                kind, name = kinds[j]
                grams, minutes = RECIPES[name]
                if kind == "cook" and slots[j][0] + minutes <= start <= slots[j][0] + keep_days * 1440:
                    rec(i + 1, kinds + [("leftover", name)], total + grams, score + W_TIME * 1.0)

    rec(0, [], 0.0, 0.0)
    return best[0]


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

    protein = dt(client, "Protein")
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    template = [SlotSpec(tomorrow + timedelta(hours=h), None, name) for h, name in ((8, "breakfast"), (12, "lunch"), (18, "dinner"))]

    def qty(name, **fields):
        return client.upsert("QuantitySpecification", "name", P + name, {"status": "specified", **fields})

    sweep(client)
    try:
        print("[0] Fixtures: five recipes, a MealPlan and a hard daily protein range...")
        hierarchy = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
        profiles = {}
        for name, (grams, minutes) in RECIPES.items():
            dish = client.upsert("DomainType", "name", f"{P}{name} dish", {"hierarchy": hierarchy, "isLookupBearing": True})
            profiles[name] = client.upsert("NutrientProfile", "name", f"{P}{name} protein profile", {
                "isAbout": dish, "forNutrient": protein, "amount": grams, "basis": "per_100g", "provenance": "sourced"})
            recipe = client.upsert("RecipeIdentity", "name", f"{P}{name} recipe", {"isRetired": False})
            plan = client.upsert("Plan", "name", P + name, {
                "specializationOf": recipe, "estimatedDurationMinutes": minutes,
                "hasRecipeYield": qty(f"{name} yield", value=1.0, unit="servings")})
            step = client.upsert("Step", "name", f"{P}{name} step", {"plan": plan, "instanceOf": dt(client, "Braising")})
            client.upsert("Specification", "name", f"{P}{name} output", {
                "step": step, "hasParticipationRole": "output", "specifies": dish, "isOptional": False,
                "hasSpecifiedQuantity": qty(f"{name} output qty", value=100.0, unit="g")})
        range_id = qty("protein range", minValue=FLOOR, maxValue=CEILING, unit="g")
        target = client.upsert("NutritionTarget", "name", P + "hard daily protein", {
            "forNutrient": protein, "hasTargetRange": range_id, "hasTimeScope": "daily",
            "dayBoundaryRule": "midnight", "strictness": "hard", "weight": W_TARGET})
        week = client.upsert("MealPlan", "name", P + "week", {
            "timeBudgetMinutes": BUDGET, "timeBudgetWeight": W_TIME, "varietyWeight": 0.0, "stockWeight": 0.0, "wasteWeight": 0.0})
        client.patch(f"/structr/rest/MealPlan/{week}", {"hasConstraint": [target]})
        plan_ids = {name: client.get("/structr/rest/Plan", params={"name": P + name})["result"][0]["id"] for name in RECIPES}
        print(f"    {len(RECIPES)} recipes, MealPlan {week}")

        print("\n[1] Eligibility under the hard target...")
        problem = build_problem(client, week, template, now)
        eligible = {c.name for c in problem.candidates.values() if ineligible_reason(problem, 0, c) is None}
        check(eligible == {P + n for n in RECIPES},
              f"exactly the five sourced fixtures are eligible ({len(problem.candidates)} recipes read, {len(eligible)} eligible)")
        others = [c for c in problem.candidates.values() if not c.name.startswith(P)]
        check(all(ineligible_reason(problem, 0, c) for c in others),
              f"all {len(others)} other recipes are refused (placeholder, missing or unmarked nutrition): "
              + "; ".join(sorted({ineligible_reason(problem, 0, c).split(',')[0] for c in others})[:2]))
        per_serving = {c.name: c.nutrients[protein] for c in problem.candidates.values() if c.name.startswith(P)}
        check(all(abs(per_serving[P + n] - RECIPES[n][0]) < 1e-9 for n in RECIPES), "protein per serving read as 12, 10, 24, 30, 45 g")

        DAY = [(480, None), (720, None), (1080, None)]              # 08:00, 12:00, 18:00 in minutes
        print("\n[2] The best feasible day (no leftovers)...")
        want = best_objective(list(RECIPES), DAY)
        result = plan_week(client, week, template, now, leftovers=False)
        check(result.feasible and result.search.proven, "a feasible plan exists and the search proved its optimality")
        check(abs(result.evaluation.objective - want) < 1e-9, f"best score {want:.4f} by enumeration (planner: {result.evaluation.objective:.4f})")
        total = sum(per_serving[d["recipe"]] for d in result.evaluation.slot_details)
        check(FLOOR <= total <= CEILING, f"the day's protein is {total:g} g, inside {FLOOR:g}-{CEILING:g}")
        wide = beam(build_problem(client, week, template, now, leftovers=False), width=100)
        check(wide.best is not None and abs(wide.best.objective - want) < 1e-9, "beam search (width 100) reaches the same score")
        print("    " + result.text().replace("\n", "\n    "))

        print("\n[2b] With leftovers allowed (the live Cooked Leftover keeping time)...")
        want = best_objective(list(RECIPES), DAY, leftovers=True)
        result = plan_week(client, week, template, now)
        check(abs(result.evaluation.objective - want) < 1e-9,
              f"best score {want:.4f} by enumeration, leftovers included (planner: {result.evaluation.objective:.4f})")
        print("    " + result.text().replace("\n", "\n    "))

        print("\n[3] Commit, then judge the day with nutrition_report()...")
        committed = plan_week(client, week, template, now, commit=True, name_prefix=P, leftovers=False)
        check(len(committed.committed) == 3, "three MealPlanEntries were written")
        rows = [r for r in nutrition_report(client, week) if r["target"] == P + "hard daily protein"]
        check(len(rows) == 1 and rows[0]["status"] == "ok" and abs(rows[0]["total"] - total) < 1e-9,
              f"nutrition_report judges the day ok at {total:g} g (report: {[(r['group'], r['status'], r['total']) for r in rows]})")

        print("\n[4] Planning again with the entries in place...")
        entries = [e for e in client.get_all("MealPlanEntry")["result"] if e["name"].startswith(P)]
        check(len(entries) == 3, "committing did not duplicate anything")
        again = plan_week(client, week, [], now)
        check(again.feasible and all(s.fixed for s in again.problem.slots) and len(again.problem.slots) == 3,
              "the three entries are read back as fixed slots and the day is still feasible")

        print("\n[5] A minimum no menu can reach...")
        for e in entries:
            client.delete(f"/structr/rest/MealPlanEntry/{e['id']}")
        client.patch(f"/structr/rest/QuantitySpecification/{range_id}", {"minValue": 140.0})
        impossible = plan_week(client, week, template, now, commit=True, name_prefix=P, leftovers=False)
        check(not impossible.feasible and impossible.diagnosis is not None and impossible.diagnosis.proven,
              "no feasible plan, and the verdict is proven")
        (violation,) = impossible.diagnosis.violations
        check(violation.kind == "below_min" and abs(violation.total - 135.0) < 1e-9 and violation.bound == 140.0,
              f"the closest plan reaches 135 g against 140 g, 5 g short ({violation.total:g} g)")
        check(impossible.committed == [] and not [e for e in client.get_all("MealPlanEntry")["result"] if e["name"].startswith(P)],
              "nothing was written")
        client.patch(f"/structr/rest/QuantitySpecification/{range_id}", {"minValue": FLOOR})

        print("\n[6] A figure switched to placeholder is left out...")
        client.patch(f"/structr/rest/NutrientProfile/{profiles['omelette']}", {"provenance": "placeholder"})
        without = [n for n in RECIPES if n != "omelette"]
        want = best_objective(without, DAY)
        result = plan_week(client, week, template, now, leftovers=False)
        used = {d["recipe"] for d in result.evaluation.slot_details}
        check(P + "omelette" not in used and abs(result.evaluation.objective - want) < 1e-9,
              f"the plan avoids the omelette and scores {want:.4f} (planner: {result.evaluation.objective:.4f})")
        client.patch(f"/structr/rest/NutrientProfile/{profiles['omelette']}", {"provenance": "sourced"})

        print("\n[7] An entry already in the plan counts towards the day...")
        region = client.upsert("TemporalRegion", "name", P + "lunch region", {
            "hasBeginning": (tomorrow + timedelta(hours=12)).strftime(FMT), "hasEnd": (tomorrow + timedelta(hours=13)).strftime(FMT)})
        client.upsert("MealPlanEntry", "name", P + "lunch chicken salad", {
            "memberOf": week, "isAbout": region, "references": plan_ids["chicken salad"], "hasPlannedServings": 1.0, "isSkipped": False})
        want = best_objective(list(RECIPES), [(480, None), (720, "chicken salad"), (1080, None)])
        result = plan_week(client, week, [template[0], template[2]], now, leftovers=False)
        check(result.feasible and abs(result.evaluation.objective - want) < 1e-9,
              f"breakfast and dinner are planned around the 30 g lunch: best score {want:.4f} (planner: {result.evaluation.objective:.4f})")
        client.delete(f"/structr/rest/MealPlanEntry/{client.get('/structr/rest/MealPlanEntry', params={'name': P + 'lunch chicken salad'})['result'][0]['id']}")

        print("\n[8] Cook once, eat twice...")
        client.patch(f"/structr/rest/MealPlan/{week}", {"hasConstraint": []})
        two = [SlotSpec(tomorrow + timedelta(hours=18), None, "monday"), SlotSpec(tomorrow + timedelta(days=1, hours=18), None, "tuesday")]
        problem = build_problem(client, week, two, now)
        stew = problem.candidates[plan_ids["braised chicken"]]
        check(stew.leftover_days == 3.0, f"the keeping time is the live Cooked Leftover default, 3 days (read: {stew.leftover_days})")
        picks = (Pick(candidate=stew.id), Pick(source=0))
        ev = evaluate(problem, picks)
        check(ev.feasible and [d["cooked_servings"] for d in ev.slot_details] == [2.0, 0.0],
              "the leftover is legal and the cook is planned for two servings")
        ids = commit_plan(client, week, problem, ev, name_prefix=P)
        cook, reheat = (client.get_all("MealPlanEntry", i)["result"] for i in ids)
        check(cook.get("hasPlannedServings") == 2.0 and (cook.get("references") or {}).get("id") == stew.id,
              "the cook entry references the recipe for 2 servings")
        check((reheat.get("consumesLeftoverFrom") or {}).get("id") == cook["id"] and not reheat.get("references"),
              "the leftover entry names its source and no recipe (invariant 7 accepted it)")
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
