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

from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.inventory import eligible_on_hand_with_urgency
from mealplanner.typetree import ancestors_or_self
from mealplanner.material_accounting import recipe_servings, candidate_input_requirements
from mealplanner.unit_conversion import convert_to_grams

MAX_POLICY_ANCESTORS = 12


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


@dataclass
class PolicyResolution:
    """The StockPolicy (or tied set of them) governing one DomainType."""
    root_type_id: str                 # the type the governing policy applies to
    distance: int                     # 0 = the type itself, n = nth ancestor
    policy_names: list[str]
    tied: bool                        # several policies on the same type
    eligible_when_opened: bool | None
    eligible_when_sealed: bool | None
    storage_conditions: set[str] | None
    include_subtypes: bool
    targets: list[tuple[str, float | None, str | None]] = field(default_factory=list)  # (policy, value, unit)

    def eligibility_kwargs(self) -> dict:
        return {
            "eligible_when_opened": self.eligible_when_opened,
            "eligible_when_sealed": self.eligible_when_sealed,
            "eligible_storage_condition_names": self.storage_conditions,
            "include_subtypes": self.include_subtypes,
        }


def combine_policy_fields(policies: list[dict]) -> dict:
    """Restrictively combine policies that govern the same type. Each
    dict has eligibleWhenOpened / eligibleWhenSealed (bool or None),
    storage (set of names or None), includesSubtypes (bool or None).

    A flag is None for "no constraint"; stock counts only if every
    policy that states a flag allows it, so the result is the AND of the
    stated flags and the INTERSECTION of the stated storage sets. That is
    order-independent and can only shrink what counts as usable stock,
    never grow it. includesSubtypes is False if any policy says False;
    an unset value is treated as True, the behaviour before this flag
    was read at all."""
    def flag(key):
        stated = [p[key] for p in policies if p[key] is not None]
        return all(stated) if stated else None

    sets = [p["storage"] for p in policies if p["storage"] is not None]
    storage = set.intersection(*[set(x) for x in sets]) if sets else None
    return {
        "eligibleWhenOpened": flag("eligibleWhenOpened"),
        "eligibleWhenSealed": flag("eligibleWhenSealed"),
        "storage": storage,
        "includesSubtypes": all(p["includesSubtypes"] is not False for p in policies),
    }


def resolve_stock_policy(client, domain_type_id: str) -> PolicyResolution | None:
    """The StockPolicy governing a DomainType, or None if none does.

    Walks from the type up through its ancestors and stops at the first
    level that has an applicable policy -- the same "most specific type
    wins" rule resolveDefault uses (Sec 8). A policy on an ANCESTOR
    applies only if its includesSubtypes isn't False; a policy on the
    type itself always applies. Several policies on the same type are
    combined restrictively (combine_policy_fields) and flagged `tied`.

    Replaces stock_policy_filters(), which took the first policy on the
    exact type only: arbitrary when several targeted one type (found by
    external review -- graph order was deciding business behaviour),
    blind to a policy on an ancestor, and it never read includesSubtypes.

    NOT handled: nested policies. If policies exist on both an ancestor
    and a descendant, each type is governed by its nearest one, but the
    two stock pools overlap physically and are not reconciled (see
    net_requirements)."""
    current_id, distance, seen = domain_type_id, 0, set()
    while current_id and current_id not in seen and distance <= MAX_POLICY_ANCESTORS:
        seen.add(current_id)
        node = client.get_all("DomainType", current_id)["result"]
        applicable = []
        for ref in node.get("stockPoliciesApplying", []):
            policy = client.get_all("StockPolicy", ref["id"])["result"]
            if distance > 0 and policy.get("includesSubtypes") is False:
                continue
            applicable.append(policy)
        if applicable:
            applicable.sort(key=lambda p: p["name"])
            fields, targets = [], []
            for policy in applicable:
                conditions = policy.get("eligibleStorageConditions") or []
                fields.append({
                    "eligibleWhenOpened": policy.get("eligibleWhenOpened"),
                    "eligibleWhenSealed": policy.get("eligibleWhenSealed"),
                    "storage": {c["name"] for c in conditions} if conditions else None,
                    "includesSubtypes": policy.get("includesSubtypes"),
                })
                target_ref = policy.get("hasTargetLevel")
                if target_ref:
                    qty = client.get_all("QuantitySpecification", target_ref["id"])["result"]
                    targets.append((policy["name"], qty.get("value"), qty.get("unit")))
            combined = combine_policy_fields(fields)
            return PolicyResolution(
                root_type_id=current_id, distance=distance, policy_names=[p["name"] for p in applicable],
                tied=len(applicable) > 1, eligible_when_opened=combined["eligibleWhenOpened"],
                eligible_when_sealed=combined["eligibleWhenSealed"], storage_conditions=combined["storage"],
                include_subtypes=combined["includesSubtypes"], targets=targets,
            )
        parent = node.get("parent")
        current_id = parent["id"] if parent else None
        distance += 1
    return None


def policy_eligibility_kwargs(resolution: PolicyResolution | None) -> dict:
    """kwargs for eligible_on_hand_with_urgency: no filtering when no
    policy governs the type."""
    return resolution.eligibility_kwargs() if resolution else {}


@dataclass
class Reserved:
    """What a MealPlan's committed entries claim, at two scopes.

    by_type: grams claimed against each ingredient Type exactly as a recipe
    names it. by_subtree: for every Type, the grams claimed anywhere at or
    below it. Both are needed because stock is counted over a Type AND its
    descendants while a reservation is recorded against ONE Type, so the two
    used to live in different taxonomic scopes: a generic "Poultry" recipe saw
    a chicken reservation as nothing, and a chicken recipe saw a "Poultry"
    reservation as nothing (found by external review)."""
    by_type: dict
    by_subtree: dict

    @classmethod
    def from_by_type(cls, client, by_type: dict) -> "Reserved":
        by_subtree: dict[str, float] = {}
        for type_id, grams in by_type.items():
            for ancestor in ancestors_or_self(client, type_id):
                by_subtree[ancestor] = by_subtree.get(ancestor, 0.0) + grams
        return cls(dict(by_type), by_subtree)

    @classmethod
    def for_meal_plan(cls, client, meal_plan_id: str) -> "Reserved":
        return cls.from_by_type(client, committed_requirements(client, meal_plan_id))


def available_for_planning(
    client, domain_type_id: str, eligible: float, now: datetime, reserved: Reserved, **eligibility,
) -> float:
    """Grams a NEW demand at this Type can still claim: eligible stock minus
    what committed entries have already claimed against it.

    Stock at a Type is everything at or below it, so a claim anywhere below
    (a chicken reservation, for a Poultry demand) reduces it. A claim ABOVE it
    (a generic Poultry demand, for a chicken one) can be met from stock this
    Type doesn't have, but it also competes for the shared ancestor's stock. The
    Types form a tree, so a new demand fits exactly when, at every ancestor
    (and at the Type itself), stock in that subtree minus everything already
    claimed in that subtree is enough. The answer is the smallest such slack.

    An ancestor is only looked at when something outside this Type's own
    subtree has claimed stock there: with no outside claim its slack can't be
    tighter than this Type's own, and skipping it saves a full stock scan per
    level. `eligible` is this Type's stock, computed by the caller under the
    Type's own StockPolicy filters; those same filters are applied to the
    ancestors' stock (an approximation: nested policies can differ).

    If the Type's policy counts only stock of exactly this Type
    (include_subtypes=False), only claims against exactly this Type reduce it.
    """
    exact_only = eligibility.get("include_subtypes", True) is False
    own = reserved.by_type.get(domain_type_id, 0.0) if exact_only else reserved.by_subtree.get(domain_type_id, 0.0)
    available = eligible - own
    if exact_only:
        return max(0.0, available)
    ancestor_filters = dict(eligibility, include_subtypes=True)
    for ancestor in ancestors_or_self(client, domain_type_id)[1:]:
        claimed_there = reserved.by_subtree.get(ancestor, 0.0)
        if claimed_there - own <= 0:
            continue
        stock, _ = eligible_on_hand_with_urgency(client, ancestor, now, **ancestor_filters)
        available = min(available, stock - claimed_there)
    return max(0.0, available)


def _target_grams(client, resolution: PolicyResolution) -> float:
    """Largest target level among the governing policies, in grams.
    Raises rather than dropping a target whose unit won't convert -- a
    silently ignored target quietly understates the shopping list."""
    grams = []
    for name, value, unit in resolution.targets:
        if value is None:
            continue
        converted = convert_to_grams(client, resolution.root_type_id, value, unit)
        if converted is None:
            raise ValueError(f"StockPolicy {name!r}: target {value} {unit!r} doesn't convert to grams")
        grams.append(converted)
    return max(grams) if grams else 0.0


def net_requirements(client, meal_plan_id: str, now: datetime) -> dict[str, float]:
    """AcquisitionList's formula (data-model.md's Recipes/plans/policies
    table) and invariant 28: how many grams need buying this week, keyed
    by stock pool. Only pools with a positive net need are included (a
    real shopping list, not a full inventory dump).

    Stock is accounted in POOLS, one per governing policy root (or per
    ingredient type when no policy governs it). A recipe's demand for an
    ingredient goes to the pool of the policy that governs that
    ingredient (resolve_stock_policy), so demand for a subtype and a
    target level set on its ancestor compete for the same stock instead
    of each claiming it separately:

        net[pool] = max(0, committed demand in the pool
                           + the pool's target level
                           - eligibleOnHand[pool under the policy's filters])

    Target levels come from StockPolicy.hasTargetLevel converted to
    grams (a target in cups used to be read as grams). Tied policies on
    one type use the largest target. Because a pool is keyed by its
    policy's type, a shortfall in a subtype's stock appears under the
    ancestor the policy names.

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

    KNOWN LIMIT: the model's formula also divides by "the yield factor of any
    trimming/prep transformation between the purchased form and the required
    form" (a recipe needing 180g diced onion, bought whole). There is no
    vocabulary yet distinguishing a Type's purchased form from its
    as-required form, so that division isn't applied; amounts are in the
    recipe's own required form. Flagged, not silently assumed away."""
    pools: dict[str, dict] = {}

    def pool_for(type_id: str) -> dict:
        resolution = resolve_stock_policy(client, type_id)
        root = resolution.root_type_id if resolution else type_id
        if root not in pools:
            pools[root] = {
                "demand": 0.0, "resolution": resolution,
                "target": _target_grams(client, resolution) if resolution else 0.0,
            }
        return pools[root]

    for type_id, grams in committed_requirements(client, meal_plan_id).items():
        pool_for(type_id)["demand"] += grams
    for policy in client.get_all("StockPolicy")["result"]:
        if policy.get("appliesTo"):
            pool_for(policy["appliesTo"]["id"])

    # The NEAREST policy owns the physical stock. A pool for a Type that has
    # another pool nested below it leaves that nested stock out of its own
    # count, or the same flour would satisfy both "keep 2 kg of flour" and
    # "keep 1 kg of bread flour". (Found by external review; before this,
    # nested pools were left as independent accounting universes.)
    chains = {root: ancestors_or_self(client, root) for root in pools}
    net: dict[str, float] = {}
    for root, pool in pools.items():
        resolution = pool["resolution"]
        counts_subtree = resolution.include_subtypes if resolution else True
        nested = {other for other in pools if other != root and root in chains[other]} if counts_subtree else set()
        eligible, _ = eligible_on_hand_with_urgency(
            client, root, now, exclude_types=nested, **policy_eligibility_kwargs(resolution),
        )
        remainder = pool["demand"] + pool["target"] - eligible
        if remainder > 0:
            net[root] = remainder
    return net
