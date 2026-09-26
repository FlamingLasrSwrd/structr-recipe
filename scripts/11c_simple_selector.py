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

Per-serving, not whole-batch, and judged at each target's own scope
(mealplanner/nutrition_scope.py): a per_meal target compares one
serving; a daily or weekly target sums the meals already planned in
that day/week and adds the candidate. Found by external review -- this
used to compare a single meal against a daily range whatever the
target's hasTimeScope said. Servings come from Plan.hasRecipeYield in
servings (data-model.md Rev 4.3); an unset or non-serving yield makes
the amount unknown, not 1.

  - SOFT, stock coverage: fraction of a candidate's raw-ingredient
    requirements already AVAILABLE -- eligibleOnHand (not expired)
    minus whatever this MealPlan's own already-committed entries have
    already claimed (mealplanner/reservation.py) -- 1.0 means no
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
why). Which stock counts for an ingredient is set by the StockPolicy
that governs its type (mealplanner/reservation.py resolve_stock_policy):
nearest policy up the type hierarchy wins, a policy on an ancestor
reaches descendants only if includesSubtypes isn't False, and several
policies on one type combine restrictively. The policy's opened/sealed,
storage-condition and includesSubtypes settings all apply. Exclusions
are transitive through both hierarchies (excluded_domain_type_ids), and
a Plan's intermediates are not treated as raw stock requirements
(material_accounting.candidate_input_requirements).

Run with: python3 scripts/11c_simple_selector.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.inventory import eligible_on_hand_with_urgency, subtypes_of
from mealplanner.material_accounting import candidate_input_requirements, plan_specifications
from mealplanner.nutrition_scope import (
    DEFAULT_SERVINGS_EATEN, scope_total, serving_nutrient_amount, target_scope_problem,
)
from mealplanner.reservation import (
    Reserved, available_for_planning, policy_eligibility_kwargs, resolve_stock_policy,
)

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
VARIETY_CAP_DAYS = 14.0
WASTE_URGENCY_WINDOW_DAYS = 5.0


def _banned_by(client, target_id: str) -> set[str]:
    """Every DomainType an exclusion of `target_id` bans.

    Transitive in both hierarchies. For an excluded type T:
      1. T and every DESCENDANT of T are banned (excluding Tree Nut bans
         a sub-origin such as Cashew; excluding Beef bans every kind of
         beef).
      2. Every food whose Biological Origin is T or any descendant of T
         is banned, together with that food's own descendants (a roasted
         form of an excluded nut is still that nut).
    Found by external review: this used to ban only T and foods linked
    DIRECTLY to T, so a food whose origin was a child of the excluded
    origin, or a subtype of an excluded food, slipped through -- for an
    allergy, the dangerous direction to be wrong in.

    Not banned: a type ABOVE an excluded one. A recipe that calls for
    generic "Poultry" while only chicken is excluded can be made with
    something else, so it isn't a hard violation; a recipe that names the
    excluded type itself is."""
    banned_roots = subtypes_of(client, target_id)
    banned = set(banned_roots)
    for root_id in banned_roots:
        for food in client.get_all("DomainType", root_id)["result"].get("foodsOfThisOrigin", []):
            banned |= subtypes_of(client, food["id"])
    return banned


def excluded_domain_type_ids(client) -> set[str]:
    """Every DomainType a HARD ExclusionConstraint bans."""
    excluded: set[str] = set()
    for ec in client.get_all("ExclusionConstraint")["result"]:
        if ec.get("strictness") == "hard" and ec.get("appliesTo"):
            excluded |= _banned_by(client, ec["appliesTo"]["id"])
    return excluded


def soft_exclusions(client) -> list[tuple[str, float, set[str]]]:
    """(constraint name, weight, banned type ids) for every SOFT
    ExclusionConstraint. These used to do nothing at all: ExclusionConstraint
    inherits strictness and weight from PlanningConstraint, but only "hard"
    was ever read, so a soft exclusion was silently inert (found by external
    review). A soft exclusion is a preference against, not a ban: a candidate
    that needs a banned type loses `weight` from its score."""
    out = []
    for ec in client.get_all("ExclusionConstraint")["result"]:
        if ec.get("strictness") == "soft" and ec.get("appliesTo"):
            out.append((ec["name"], _number(ec.get("weight"), 0.0), _banned_by(client, ec["appliesTo"]["id"])))
    return out


def _number(value, default: float) -> float:
    """`default` only when the value is MISSING. `value or default` also
    replaced a legitimate 0 -- a zero weight (ignore this term) became 0.5,
    and a zero time budget became 60 -- which is domain data being overwritten
    by a fallback (found by external review)."""
    return default if value is None else value


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


def candidate_consumed_types(client, plan: dict) -> set[str]:
    """The DomainTypes a cook would actually use or eat, for exclusion
    purposes: the types named by INPUT and OUTPUT Specifications that are not
    optional.

    It used to be every Specification's type regardless of role. That
    rejected a recipe for an excluded INSTRUMENT (equipment isn't eaten) and
    for an OPTIONAL ingredient (it can simply be omitted), which are wrong
    the other way from the allergy bug. Outputs count because the finished
    dish is what is eaten: a recipe whose output is an excluded type makes
    it. Intermediates are included as outputs too, conservatively."""
    consumed = set()
    for spec in plan_specifications(client, plan):
        if spec.get("hasParticipationRole") == "instrument" or spec.get("isOptional"):
            continue
        if spec.get("specifies"):
            consumed.add(spec["specifies"]["id"])
    return consumed


def candidate_optional_types(client, plan: dict) -> set[str]:
    """Types the recipe lists only as optional input, for a note: a recipe
    with an excluded OPTIONAL ingredient isn't rejected, but the user should
    be told to leave it out."""
    return {
        spec["specifies"]["id"] for spec in plan_specifications(client, plan)
        if spec.get("isOptional") and spec.get("hasParticipationRole") == "input" and spec.get("specifies")
    }


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


def stock_and_waste_scores(
    client, plan: dict, now: datetime, reserved: Reserved
) -> tuple[float | None, float, list[str]]:
    """(stock_coverage in [0,1] or None if no comparable inputs,
    waste_urgency in [0,1], notes).

    `reserved`: mealplanner/reservation.py's Reserved (what this MealPlan's
    committed entries claim, exactly and per subtree), computed once by select() and
    passed in here rather than recomputed per candidate. Subtracted
    from eligibleOnHand before scoring coverage -- fixes a gap found by
    external review: two candidates scored in the same run used to both
    see the SAME on-hand stock as 100% available, because nothing
    accounted for what this MealPlan's own already-committed entries
    already claim. See mealplanner/reservation.py's module docstring
    for what "committed" means and its scope (fresh-cooking entries
    only, not leftover-consuming ones)."""
    requirements = candidate_input_requirements(client, plan)
    if not requirements:
        return None, 0.0, []

    coverages = []
    max_urgency = 0.0
    notes = []
    for domain_type_id, required_qty in requirements:
        # If a StockPolicy applies to this ingredient, honor its
        # opened-status AND storage-condition eligibility filters
        # (mealplanner/opened_status_schema.py,
        # mealplanner/storage_condition_schema.py) -- previously
        # eligible_on_hand had no filtering at all on either dimension,
        # a gap flagged in the holes-and-gaps analysis.
        policy = resolve_stock_policy(client, domain_type_id)
        eligible, soonest_days = eligible_on_hand_with_urgency(
            client, domain_type_id, now, **policy_eligibility_kwargs(policy),
        )
        available = available_for_planning(
            client, domain_type_id, eligible, now, reserved, **policy_eligibility_kwargs(policy),
        )
        coverage = min(1.0, available / required_qty) if required_qty else 0.0
        coverages.append(coverage)
        type_name = client.get_all("DomainType", domain_type_id)["result"].get("name")
        note = f"{type_name}: {available:.0f}g available ({eligible:.0f}g eligible) / {required_qty:.0f}g needed ({coverage:.0%} covered)"
        if soonest_days is not None:
            urgency = max(0.0, 1.0 - soonest_days / WASTE_URGENCY_WINDOW_DAYS) if soonest_days >= 0 else 0.0
            max_urgency = max(max_urgency, urgency)
            note += f", soonest expiry in {soonest_days:.1f}d (urgency={urgency:.2f})"
        if policy and policy.tied:
            note += f" [{len(policy.policy_names)} policies tie on this type; combined restrictively]"
        notes.append(note)

    return sum(coverages) / len(coverages), max_urgency, notes


def time_fit_score(duration_minutes: float | None, budget_minutes: float) -> float:
    if duration_minutes is None:
        return 0.5  # unknown duration -- neutral, not a penalty or a reward
    if duration_minutes <= budget_minutes:
        return 1.0
    if budget_minutes <= 0:
        return 0.0  # any time at all overshoots a zero budget; don't divide by it
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


def nutrition_terms(
    client, meal_plan: dict, plan: dict, targets: list[dict], slot_start: datetime | None,
    servings_eaten: float, planned_cache: dict,
) -> tuple[float, list[str], bool]:
    """(weighted soft nutrition score, notes, disqualified) for one
    candidate, with each NutritionTarget judged at the scope it declares
    (mealplanner/nutrition_scope.py explains the semantics).

    per_meal: this candidate's servings against the range, as before.
    daily/weekly: the nutrient already planned in that scope plus this
    candidate's. A scoped MAXIMUM can disqualify on a hard target
    because totals only grow; a scoped MINIMUM never disqualifies here
    (the scope may simply be unfilled) and is judged by
    nutrition_report() instead. A candidate with no nutrient data for a
    target is neutral, as before; a target that can't be evaluated is
    named in the notes rather than silently dropped."""
    term, notes, disqualified = 0.0, [], False
    for target in targets:
        nutrient, target_range = target.get("forNutrient"), target.get("hasTargetRange")
        if not nutrient or not target_range:
            continue
        rng = client.get_all("QuantitySpecification", target_range["id"])["result"]
        min_val, max_val = rng.get("minValue"), rng.get("maxValue")
        problem = target_scope_problem(target, rng.get("unit"))
        if problem:
            notes.append(f"{nutrient['name']}: target not evaluated -- {problem}")
            continue
        per_serving = serving_nutrient_amount(client, plan, nutrient["id"])
        if per_serving is None:
            continue
        intake = per_serving * servings_eaten
        scope, hard = target["hasTimeScope"], target.get("strictness") == "hard"

        planned_total, caveats = 0.0, []
        if scope == "daily" and slot_start is None:
            if hard and max_val is not None and intake > max_val:
                disqualified = True
                notes.append(f"{nutrient['name']}={intake:.1f}g in one meal already exceeds HARD daily max {max_val}")
            else:
                notes.append(f"{nutrient['name']}: daily target not scored (no slot_start given)")
            continue
        if scope in ("daily", "weekly"):
            key = (nutrient["id"], scope, slot_start.astimezone(timezone.utc).date() if scope == "daily" else None)
            if key not in planned_cache:
                planned_cache[key] = scope_total(client, meal_plan, nutrient["id"], scope, slot_start)
            planned = planned_cache[key]
            planned_total = planned.total
            if planned.unknown:
                caveats.append(f"{len(planned.unknown)} planned meal(s) have no nutrient data")
            if planned.assumed_default_servings:
                caveats.append(f"{len(planned.assumed_default_servings)} planned meal(s) assumed {DEFAULT_SERVINGS_EATEN:g} serving")

        actual = planned_total + intake
        over_max = max_val is not None and actual > max_val
        under_min = min_val is not None and actual < min_val
        violated = (over_max or under_min) if scope == "per_meal" else over_max
        label = f"{nutrient['name']}={actual:.1f}g {scope}"
        if scope != "per_meal":
            label += f" (planned {planned_total:.1f} + this {intake:.1f})"
        if caveats:
            label += " [" + "; ".join(caveats) + "]"
        if hard and violated:
            disqualified = True
            notes.append(f"{label} outside HARD range [{min_val},{max_val}]")
        else:
            fit = nutrition_fit_score(actual, min_val, max_val)
            term += _number(target.get("weight"), 0.0) * fit
            notes.append(f"{label} fit={fit:.2f}")
            if hard and under_min:
                notes.append(f"{nutrient['name']}: HARD {scope} minimum {min_val} can only be judged once the scope is filled (nutrition_report)")
    return term, notes, disqualified


def select(
    client, meal_plan_id: str, now: datetime, meal_type: str | None = None,
    slot_start: datetime | None = None, servings_eaten: float = DEFAULT_SERVINGS_EATEN,
) -> list[dict]:
    """Returns candidates ranked best-first: [{plan, score, disqualified, reason}, ...].

    meal_type: if given (e.g. "Dinner"), candidates whose RecipeIdentity
    isn't tagged with it are disqualified -- including recipes with NO
    tags at all (prep steps, structural test fixtures).

    slot_start: when the meal being chosen will start. Needed to score
    any `daily` NutritionTarget, which sums the meals already planned on
    the same calendar day; without it daily targets are skipped (noted in
    the result) rather than judged against one meal in isolation.
    servings_eaten: how many servings the candidate contributes to
    intake (default: one person, one serving)."""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    time_budget = _number(meal_plan.get("timeBudgetMinutes"), 60.0)
    time_weight = _number(meal_plan.get("timeBudgetWeight"), 0.5)
    variety_weight = _number(meal_plan.get("varietyWeight"), 0.5)
    stock_weight = _number(meal_plan.get("stockWeight"), 0.0)
    waste_weight = _number(meal_plan.get("wasteWeight"), 0.0)

    excluded = excluded_domain_type_ids(client)
    soft = soft_exclusions(client)
    nutrition_targets = active_nutrition_targets(client, meal_plan)
    all_plans = client.get_all("Plan")["result"]
    # Computed once per select() call, not once per candidate -- what
    # this MealPlan's own already-committed entries claim, so every
    # candidate scored in this run sees the same, correctly-reduced
    # on-hand picture instead of each seeing the full amount as if the
    # others didn't exist.
    reserved = Reserved.for_meal_plan(client, meal_plan_id)
    planned_cache: dict = {}

    results = []
    for plan in all_plans:
        if meal_type is not None and meal_type not in candidate_meal_types(client, plan):
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": f"not tagged for meal type {meal_type!r}"})
            continue

        required = candidate_consumed_types(client, plan)
        hit = required & excluded
        if hit:
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": f"requires excluded ingredient(s): {hit}"})
            continue

        nutrition_term, nutrition_notes, disqualified_by_nutrition = nutrition_terms(
            client, meal_plan, plan, nutrition_targets, slot_start, servings_eaten, planned_cache,
        )

        if disqualified_by_nutrition:
            results.append({"plan": plan, "score": None, "disqualified": True,
                             "reason": "; ".join(nutrition_notes)})
            continue

        tf = time_fit_score(plan.get("estimatedDurationMinutes"), time_budget)
        vs = variety_score(client, plan["id"], now)
        stock_coverage, waste_urgency, stock_notes = stock_and_waste_scores(client, plan, now, reserved)
        stock_term = stock_weight * (stock_coverage or 0.0)
        waste_term = waste_weight * waste_urgency
        soft_hits = [(name, weight) for name, weight, banned in soft if required & banned]
        soft_penalty = sum(weight for _, weight in soft_hits)
        score = time_weight * tf + variety_weight * vs + nutrition_term + stock_term + waste_term - soft_penalty
        reason = f"time_fit={tf:.2f} variety={vs:.2f}"
        if soft_hits:
            reason += " " + "; ".join(f"soft exclusion {name!r} costs {weight:g}" for name, weight in soft_hits)
        optional_banned = candidate_optional_types(client, plan) & excluded
        if optional_banned:
            names = sorted(client.get_all("DomainType", i)["result"]["name"] for i in optional_banned)
            reason += f" [leave out the optional excluded ingredient(s): {', '.join(names)}]"
        if nutrition_notes:
            reason += " " + "; ".join(nutrition_notes)
        if stock_notes:
            reason += " " + "; ".join(stock_notes)
        results.append({"plan": plan, "score": score, "disqualified": False, "reason": reason})

    # `score or -1` treated a score of exactly 0 as worse than a negative one,
    # which soft exclusions can now produce; compare against None explicitly.
    results.sort(key=lambda r: (r["disqualified"], -(r["score"] if r["score"] is not None else 0.0)))
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
