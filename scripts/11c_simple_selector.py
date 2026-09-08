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
  - HARD: a meal_type filter (e.g. "Dinner") disqualifies any candidate
    whose RecipeIdentity isn't tagged with it -- including untagged
    recipes (prep steps, structural test fixtures), which is what keeps
    them out of the pool without a separate "is this a real meal"
    concept. See mealplanner/meal_type_schema.py for why this is
    Concept-scheme tagging, not a class or a plain enum property.
  - HARD: any Specification in the candidate whose `specifies` matches
    an active hard ExclusionConstraint, directly or via
    hasBiologicalOrigin, disqualifies the candidate outright. A HARD
    NutritionTarget whose range the candidate falls outside also
    disqualifies -- same hard/soft mechanism, same code path.
  - SOFT, time fit: 1.0 if within the week's time budget, degrading
    linearly past it.
  - SOFT, variety: bonus for not having been planned recently (capped
    at a 14-day window; never-used gets the max bonus).
  - SOFT, nutrition fit: how well the candidate's output NutrientProfile
    fits each active (MealPlan.hasConstraint-attached) NutritionTarget's
    range, weighted by that NutritionTarget's own `weight`.

Nutrition data source: Sec 8 rule 7(a) only -- the output Food-Identity
Type's OWN NutrientProfile (analytically measured, or here, a flagged
placeholder). Rule 7(b) (yield/retention-factor-derived from raw
ingredients) is NOT implemented -- it needs RetentionFactor
DefaultSpecifications wired up per-ingredient-per-transformation, real
curation work, deferred rather than faked. A candidate with no
NutrientProfile for a given target's nutrient is neither penalized nor
rewarded (neutral, same convention as unknown duration).

Batch-vs-serving caveat: this compares the WHOLE OUTPUT BATCH's
nutrition against the target range, not a per-serving amount --
Plan.hasRecipeYield isn't currently expressed in a way that cleanly
converts to a serving count (see mealplanner/domain_invariants.py's
notes on what's deferred). A real per-serving comparison is a natural
refinement once that's sorted out; flagged here rather than quietly
assumed correct.

  - SOFT, stock coverage: fraction of a candidate's raw-ingredient
    requirements already eligibleOnHand (not expired) -- 1.0 means no
    shopping needed for that ingredient. Averaged across the
    candidate's input Specifications that have a quantity.
  - SOFT, waste avoidance: bonus for using up on-hand stock that's
    close to expiring. Highest when the candidate's inputs match stock
    expiring soon; zero if nothing relevant is on hand or expiring.
    Uses eligible_on_hand_with_urgency's soonest-expiry figure against
    a 5-day urgency window.

Stock/waste data source: mealplanner/inventory.py's currentMagnitude()/
physicalOnHand()/eligibleOnHand(), built the same way as this selector
(Python over REST, not StructrScript -- see that module's docstring for
why). Storage-condition/opened-status eligibility filtering is NOT
implemented there (a real, flagged scope cut, not an oversight) --
eligibility here means "not expired" only.

Run with: python3 scripts/11c_simple_selector.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.inventory import eligible_on_hand_with_urgency

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
VARIETY_CAP_DAYS = 14.0
WASTE_URGENCY_WINDOW_DAYS = 5.0


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


def candidate_meal_types(client, plan: dict) -> set[str]:
    """The Concept names (e.g. {"Dinner"}) the Plan's RecipeIdentity is
    tagged with. A Plan with no specializationOf, or a RecipeIdentity
    with no tags at all, returns an empty set -- deliberately: an
    untagged recipe (a prep step, a structural test fixture) never
    matches a meal-type filter, which is what keeps it out of the
    candidate pool without needing a separate "is this a real meal"
    concept."""
    recipe_ref = plan.get("specializationOf")
    if not recipe_ref:
        return set()
    recipe = client.get_all("RecipeIdentity", recipe_ref["id"])["result"]
    return {c["name"] for c in recipe.get("hasMealType", [])}


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


def candidate_output(client, plan: dict) -> tuple[str | None, float | None]:
    """(output DomainType id, output batch quantity in its stated unit)
    for a Plan's FIRST output-role Specification. None if it has none."""
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasParticipationRole") != "output":
                continue
            specifies = spec.get("specifies")
            qty_ref = spec.get("hasSpecifiedQuantity")
            if not specifies:
                continue
            qty = None
            if qty_ref:
                qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"].get("value")
            return specifies["id"], qty
    return None, None


def nutrient_profile_amount(client, output_type_id: str, nutrient_id: str) -> float | None:
    """Per-100g amount from the output type's own NutrientProfile for
    this nutrient (Sec 8 rule 7(a) only -- see module docstring)."""
    output_type = client.get_all("DomainType", output_type_id)["result"]
    for profile_ref in output_type.get("nutrientProfilesAbout", []):
        profile = client.get_all("NutrientProfile", profile_ref["id"])["result"]
        if (profile.get("forNutrient") or {}).get("id") == nutrient_id and profile.get("basis") == "per_100g":
            return profile.get("amount")
    return None


def active_nutrition_targets(client, meal_plan: dict) -> list[dict]:
    return [
        client.get_all("NutritionTarget", c["id"])["result"]
        for c in meal_plan.get("hasConstraint", [])
        if c["type"] == "NutritionTarget"
    ]


def nutrition_fit_score(actual: float, min_val: float | None, max_val: float | None) -> float:
    if min_val is not None and actual < min_val:
        return max(0.0, 1.0 - (min_val - actual) / min_val) if min_val else 0.0
    if max_val is not None and actual > max_val:
        return max(0.0, 1.0 - (actual - max_val) / max_val) if max_val else 0.0
    return 1.0


def candidate_input_requirements(client, plan: dict) -> list[tuple[str, float]]:
    """[(input DomainType id, required quantity), ...] for a Plan's
    input-role Specifications that carry a quantity. Instrument-role
    Specifications never have one (invariant 6); input Specifications
    without a quantity (e.g. "1 whole onion") are skipped here since
    there's no comparable magnitude to check against on-hand stock."""
    requirements = []
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasParticipationRole") != "input":
                continue
            specifies = spec.get("specifies")
            qty_ref = spec.get("hasSpecifiedQuantity")
            if not specifies or not qty_ref:
                continue
            qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"].get("value")
            if qty:
                requirements.append((specifies["id"], qty))
    return requirements


def stock_and_waste_scores(client, plan: dict, now: datetime) -> tuple[float | None, float, list[str]]:
    """(stock_coverage in [0,1] or None if no comparable inputs,
    waste_urgency in [0,1], notes)."""
    requirements = candidate_input_requirements(client, plan)
    if not requirements:
        return None, 0.0, []

    coverages = []
    max_urgency = 0.0
    notes = []
    for domain_type_id, required_qty in requirements:
        eligible, soonest_days = eligible_on_hand_with_urgency(client, domain_type_id, now)
        coverage = min(1.0, eligible / required_qty) if required_qty else 0.0
        coverages.append(coverage)
        type_name = client.get_all("DomainType", domain_type_id)["result"].get("name")
        note = f"{type_name}: {eligible:.0f}g on hand / {required_qty:.0f}g needed ({coverage:.0%} covered)"
        if soonest_days is not None:
            urgency = max(0.0, 1.0 - soonest_days / WASTE_URGENCY_WINDOW_DAYS) if soonest_days >= 0 else 0.0
            max_urgency = max(max_urgency, urgency)
            note += f", soonest expiry in {soonest_days:.1f}d (urgency={urgency:.2f})"
        notes.append(note)

    return sum(coverages) / len(coverages), max_urgency, notes


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


def select(client, meal_plan_id: str, now: datetime, meal_type: str | None = None) -> list[dict]:
    """Returns candidates ranked best-first: [{plan, score, disqualified, reason}, ...].

    meal_type: if given (e.g. "Dinner"), candidates whose RecipeIdentity
    isn't tagged with it are disqualified -- including recipes with NO
    tags at all (prep steps, structural test fixtures)."""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    time_budget = meal_plan.get("timeBudgetMinutes") or 60.0
    time_weight = meal_plan.get("timeBudgetWeight") or 0.5
    variety_weight = meal_plan.get("varietyWeight") or 0.5
    stock_weight = meal_plan.get("stockWeight") or 0.0
    waste_weight = meal_plan.get("wasteWeight") or 0.0

    excluded = excluded_domain_type_ids(client)
    nutrition_targets = active_nutrition_targets(client, meal_plan)
    all_plans = client.get_all("Plan")["result"]

    results = []
    for plan in all_plans:
        if meal_type is not None and meal_type not in candidate_meal_types(client, plan):
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": f"not tagged for meal type {meal_type!r}"})
            continue

        required = candidate_required_types(client, plan)
        hit = required & excluded
        if hit:
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": f"requires excluded ingredient(s): {hit}"})
            continue

        output_type_id, output_qty = candidate_output(client, plan)

        nutrition_term = 0.0
        nutrition_notes = []
        disqualified_by_nutrition = False
        for target in nutrition_targets:
            nutrient = target.get("forNutrient")
            target_range = target.get("hasTargetRange")
            if not nutrient or not target_range or not output_type_id or output_qty is None:
                continue
            range_full = client.get_all("QuantitySpecification", target_range["id"])["result"]
            min_val, max_val = range_full.get("minValue"), range_full.get("maxValue")
            per_100g = nutrient_profile_amount(client, output_type_id, nutrient["id"])
            if per_100g is None:
                continue
            actual = output_qty * per_100g / 100.0
            fit = nutrition_fit_score(actual, min_val, max_val)
            in_range = (min_val is None or actual >= min_val) and (max_val is None or actual <= max_val)
            if target.get("strictness") == "hard" and not in_range:
                disqualified_by_nutrition = True
                nutrition_notes.append(f"{nutrient['name']}={actual:.1f}g outside HARD range [{min_val},{max_val}]")
            else:
                weight = target.get("weight") or 0.0
                nutrition_term += weight * fit
                nutrition_notes.append(f"{nutrient['name']}={actual:.1f}g fit={fit:.2f}")

        if disqualified_by_nutrition:
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": "; ".join(nutrition_notes)})
            continue

        tf = time_fit_score(plan.get("estimatedDurationMinutes"), time_budget)
        vs = variety_score(client, plan["id"], now)
        stock_coverage, waste_urgency, stock_notes = stock_and_waste_scores(client, plan, now)
        stock_term = stock_weight * (stock_coverage or 0.0)
        waste_term = waste_weight * waste_urgency
        score = time_weight * tf + variety_weight * vs + nutrition_term + stock_term + waste_term
        reason = f"time_fit={tf:.2f} variety={vs:.2f}"
        if nutrition_notes:
            reason += " " + "; ".join(nutrition_notes)
        if stock_notes:
            reason += " " + "; ".join(stock_notes)
        results.append({"plan": plan, "score": score, "disqualified": False, "reason": reason})

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

    for meal_type in [None, "Dinner"]:
        label = meal_type or "(unfiltered)"
        print(f"\nRanking candidates -- meal_type={label}...")
        ranked = select(client, meal_plan_id, now, meal_type=meal_type)
        for r in ranked:
            name = r["plan"]["name"]
            if r["disqualified"]:
                print(f"  DISQUALIFIED  {name:45s}  {r['reason']}")
            else:
                print(f"  score={r['score']:.3f}  {name:45s}  {r['reason']}")

        winner = next((r for r in ranked if not r["disqualified"]), None)
        if winner:
            print(f"  Winner: {winner['plan']['name']} (score={winner['score']:.3f})")
    return ranked


if __name__ == "__main__":
    main()
