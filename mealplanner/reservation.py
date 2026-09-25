"""The reservation layer: what a MealPlan's own committed entries have
already claimed, so a single planning session doesn't let two
candidates both count the same physical stock as available.

Fixes the "no reservation layer" gap found by external review: the
selector (scripts/11c_simple_selector.py) used to score every candidate
against RAW eligibleOnHand, so two candidates scored in the same run --
or scored one slot at a time across a week, which is how this
single-user tool is actually used -- could each independently show
100% stock coverage for the same 500g of chicken, because nothing
accounted for what an earlier, already-committed MealPlanEntry already
claims.

The reviewer's suggested vocabulary (Physical -> Eligible -> Reserved
-> Available -> Consumption) maps onto pieces that mostly already
exist:
  Physical      mealplanner/inventory.py's physical_on_hand()
  Eligible      mealplanner/inventory.py's eligible_on_hand_with_urgency()
  Reserved      committed_requirements() below -- NEW
  Available     available_for_planning() below -- NEW
  Consumption   a real cook's Allocations (already built, step 6)

This is also data-model.md's own AcquisitionList (Sec 7, computed) and
invariant 28 ("AcquisitionList counts only entries not yet fulfilledBy
a completed Process") -- both named in the model already, neither
built until now. net_requirements() below is that computation.

SCOPE, stated precisely: this module covers RAW-INGREDIENT reservation
for not-yet-fulfilled FRESH-COOKING entries (MealPlanEntry.references +
hasPlannedServings, invariant 7). It does NOT cover leftover
reservation (MealPlanEntry.consumesLeftoverFrom, invariants 23/24, the
reservation Role, targets_entry) -- a leftover-consuming entry draws on
an already-cooked surplus, a genuinely separate pool whose accounting
depends on whether its source entry has been cooked yet (a real
Allocation's output quantity) or not (expected_combination_output()'s
estimate, mealplanner/material_accounting.py). That's real, separate
work; flagged here rather than silently folded in or silently ignored.
"""

from __future__ import annotations

from datetime import datetime

from mealplanner.inventory import eligible_on_hand_with_urgency
from mealplanner.material_accounting import recipe_servings, candidate_input_requirements


def committed_requirements(client, meal_plan_id: str) -> dict[str, float]:
    """domain_type_id -> total grams this MealPlan's own committed
    entries already claim -- the "Reserved" tier between Eligible and
    Available on-hand stock.

    Invariant 28 applies here directly: a skipped entry claims nothing,
    and a FULFILLED entry's consumption is already reflected in actual
    inventory (real Allocations reduced currentMagnitude when it was
    cooked) -- counting it again here would double-subtract what's
    already gone.

    Only fresh-cooking entries claim raw-ingredient stock this way (see
    module docstring for why leftover-consuming entries are out of
    scope here)."""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    requirements: dict[str, float] = {}
    for entry_ref in meal_plan.get("hasEntry", []):
        entry = client.get_all("MealPlanEntry", entry_ref["id"])["result"]
        if entry.get("isSkipped"):
            continue
        if entry.get("fulfilledBy"):
            continue
        plan_ref = entry.get("references")
        planned_servings = entry.get("hasPlannedServings")
        if not plan_ref or planned_servings is None:
            continue  # a consumes_leftover_from entry (invariant 7) -- see module docstring
        plan = client.get_all("Plan", plan_ref["id"])["result"]
        servings = recipe_servings(client, plan)
        if not servings:
            continue
        scale = planned_servings / servings
        for domain_type_id, qty_grams in candidate_input_requirements(client, plan):
            requirements[domain_type_id] = requirements.get(domain_type_id, 0.0) + qty_grams * scale
    return requirements


def available_for_planning(eligible: float, domain_type_id: str, reserved: dict[str, float]) -> float:
    """Eligible on-hand minus what's already committed elsewhere in
    this same MealPlan -- the "Available" tier. A pure subtraction,
    floored at 0; the REST-calling work already happened to produce
    `eligible` (eligible_on_hand_with_urgency) and `reserved`
    (committed_requirements), both computed once per planning run by
    the caller rather than per candidate."""
    return max(0.0, eligible - reserved.get(domain_type_id, 0.0))


def net_requirements(client, meal_plan_id: str, now: datetime) -> dict[str, float]:
    """AcquisitionList's formula (data-model.md's Recipes/plans/policies
    table) and invariant 28: for each DomainType, how many grams need
    buying this week. Only DomainTypes with a positive net need are
    included (a real shopping list, not a full inventory dump).

    gross_need[type] = committed_requirements()[type]   (this week's
                        not-yet-fulfilled fresh-cooking entries)
                      + (any StockPolicy's hasTargetLevel for that type)
    net[type] = max(0, gross_need[type] - eligibleOnHand[type])

    RESOLVED AMBIGUITY: the model's own formula reads "...+ (StockPolicy
    shortfalls up to target level) - eligible on-hand". Taken literally
    that subtracts eligible-on-hand twice -- once implicitly inside
    "shortfall" (= target level - on-hand), then again at the end. Read
    instead as a single shared pool: on-hand stock first covers this
    week's committed recipe needs, and only what's left over after that
    also counts against the standing StockPolicy reserve target -- i.e.
    eligible-on-hand is subtracted exactly once, against the SUM of
    (this week's need + the target level), not against each term
    separately. This is also the physically sensible reading: buying
    500g today to cook Monday's dinner doesn't also refill a separate
    900g standing pantry reserve for free -- the two needs compete for
    the same purchase.

    SCOPE CUT, not resolved here: the model's formula also divides by
    "the yield factor of any trimming/prep transformation between the
    purchased form and the required form" (e.g. a recipe requiring
    180g diced onion, bought as whole onion). This project has no
    vocabulary yet distinguishing a Type's purchased form from its
    as-required form, so that division isn't applied -- the amounts
    returned here are in the recipe's OWN required form, which may
    understate a real shopping quantity for anything normally bought
    less prepared than the recipe calls for. Flagged, not silently
    assumed away, same as material_accounting.py's own open questions."""
    gross: dict[str, float] = dict(committed_requirements(client, meal_plan_id))

    for policy in client.get_all("StockPolicy")["result"]:
        applies_to = policy.get("appliesTo")
        target_ref = policy.get("hasTargetLevel")
        if not applies_to or not target_ref:
            continue
        target_level = client.get_all("QuantitySpecification", target_ref["id"])["result"].get("value")
        if target_level is None:
            continue
        type_id = applies_to["id"]
        gross[type_id] = gross.get(type_id, 0.0) + target_level

    net: dict[str, float] = {}
    for type_id, need in gross.items():
        eligible, _ = eligible_on_hand_with_urgency(client, type_id, now)
        remainder = need - eligible
        if remainder > 0:
            net[type_id] = remainder
    return net
