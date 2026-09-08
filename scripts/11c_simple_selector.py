"""The simple-path meal selector: filter by hard constraints, score
survivors by the weighted soft-constraint sum, greedily pick the best.

Deliberately NOT a StructrScript SchemaMethod -- this needs to read
across many entity types (Plan, Specification, DomainType,
ExclusionConstraint, MealPlanEntry history) and do real control flow,
which is exactly the shape that hit the recursion/complexity ceiling
found while building resolveDefault (step 3). This is application
logic that reads/writes via the REST API, matching how a real system
would run it -- the "optimizer" is a client-side concern, not a
stored procedure.

Scoring dimensions for v1 (per the design conversation):
  - HARD: any Specification in the candidate whose `specifies` matches
    an active hard ExclusionConstraint, directly or via
    hasBiologicalOrigin, disqualifies the candidate outright.
  - SOFT, time fit: 1.0 if within the week's time budget, degrading
    linearly past it.
  - SOFT, variety: bonus for not having been planned recently (capped
    at a 14-day window; never-used gets the max bonus).

Deliberately NOT scored yet: nutrition fit (NutrientProfile isn't
wired up at the recipe level -- nutrition data currently only exists
on actual cooked OUTPUTS, not on Plans, so there's nothing to score
against before cooking) and stock-awareness/waste (needs
currentMagnitude()/physicalOnHand(), still unbuilt). Both are natural
v2 additions once their underlying data exists -- noted, not faked.

Run with: python3 scripts/11c_simple_selector.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
VARIETY_CAP_DAYS = 14.0


def excluded_domain_type_ids(client) -> set[str]:
    """Every DomainType a hard ExclusionConstraint bans, directly or
    via hasBiologicalOrigin."""
    hard = client.get_all("ExclusionConstraint")["result"]
    excluded = set()
    for ec in hard:
        if ec.get("strictness") != "hard":
            continue
        applies_to = ec.get("appliesTo")
        if not applies_to:
            continue
        target_id = applies_to["id"]
        excluded.add(target_id)
        # anything whose Biological Origin IS this excluded type is
        # also excluded (e.g. Almonds -> Tree Nut)
        target_full = client.get_all("DomainType", target_id)["result"]
        for food in target_full.get("foodsOfThisOrigin", []):
            excluded.add(food["id"])
    return excluded


def candidate_required_types(client, plan: dict) -> set[str]:
    """Every DomainType a Plan's Specifications `specifies`, across all
    its Steps."""
    required = set()
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            specifies = spec.get("specifies")
            if specifies:
                required.add(specifies["id"])
    return required


def time_fit_score(duration_minutes: float | None, budget_minutes: float) -> float:
    if duration_minutes is None:
        return 0.5  # unknown duration -- neutral, not a penalty or a reward
    if duration_minutes <= budget_minutes:
        return 1.0
    overage = duration_minutes - budget_minutes
    return max(0.0, 1.0 - overage / budget_minutes)


def variety_score(client, plan_id: str, now: datetime) -> float:
    entries = client.get_all("Plan", plan_id)["result"].get("referencedByEntries", [])
    if not entries:
        return 1.0  # never used -- maximum variety bonus
    most_recent_days_ago = None
    for entry_ref in entries:
        entry = client.get_all("MealPlanEntry", entry_ref["id"])["result"]
        about = entry.get("isAbout")
        if not about:
            continue
        region = client.get_all("TemporalRegion", about["id"])["result"]
        beginning = region.get("hasBeginning")
        if not beginning:
            continue
        when = datetime.strptime(beginning, "%Y-%m-%dT%H:%M:%S%z")
        days_ago = (now - when).total_seconds() / 86400.0
        if most_recent_days_ago is None or days_ago < most_recent_days_ago:
            most_recent_days_ago = days_ago
    if most_recent_days_ago is None:
        return 1.0
    return max(0.0, min(1.0, most_recent_days_ago / VARIETY_CAP_DAYS))


def select(client, meal_plan_id: str, now: datetime) -> list[dict]:
    """Returns candidates ranked best-first: [{plan, score, disqualified, reason}, ...]"""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    time_budget = meal_plan.get("timeBudgetMinutes") or 60.0
    time_weight = meal_plan.get("timeBudgetWeight") or 0.5
    variety_weight = meal_plan.get("varietyWeight") or 0.5

    excluded = excluded_domain_type_ids(client)
    all_plans = client.get_all("Plan")["result"]

    results = []
    for plan in all_plans:
        required = candidate_required_types(client, plan)
        hit = required & excluded
        if hit:
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": f"requires excluded ingredient(s): {hit}"})
            continue
        tf = time_fit_score(plan.get("estimatedDurationMinutes"), time_budget)
        vs = variety_score(client, plan["id"], now)
        score = time_weight * tf + variety_weight * vs
        results.append({"plan": plan, "score": score, "disqualified": False,
                         "reason": f"time_fit={tf:.2f} variety={vs:.2f}"})

    results.sort(key=lambda r: (r["disqualified"], -(r["score"] or -1)))
    return results


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    meal_plan_id = client.get("/structr/rest/MealPlan", params={"name": "TEST -- Selector demo week"})["result"]
    if not meal_plan_id:
        meal_plan_id = client.post("/structr/rest/MealPlan", {
            "name": "TEST -- Selector demo week",
            "timeBudgetMinutes": 30.0, "timeBudgetWeight": 0.8, "varietyWeight": 0.2,
            "visibleToAuthenticatedUsers": True,
        })["result"][0]
    else:
        meal_plan_id = meal_plan_id[0]["id"]

    print(f"MealPlan: {meal_plan_id}")
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    print(f"  timeBudgetMinutes={meal_plan.get('timeBudgetMinutes')} "
          f"timeBudgetWeight={meal_plan.get('timeBudgetWeight')} "
          f"varietyWeight={meal_plan.get('varietyWeight')}")

    print("\nRanking candidates...")
    ranked = select(client, meal_plan_id, now)
    for r in ranked:
        name = r["plan"]["name"]
        if r["disqualified"]:
            print(f"  DISQUALIFIED  {name:45s}  {r['reason']}")
        else:
            print(f"  score={r['score']:.3f}  {name:45s}  {r['reason']}")

    winner = next((r for r in ranked if not r["disqualified"]), None)
    if winner:
        print(f"\nWinner: {winner['plan']['name']} (score={winner['score']:.3f})")
    return ranked


if __name__ == "__main__":
    main()
