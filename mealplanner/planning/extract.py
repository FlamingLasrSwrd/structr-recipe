"""The graph as a planning problem (docs/optimizer-design.md Sec 4.1, step 1).

Everything Structr knows that planning needs is read here, once, through a
ReadCache, using the engines the rest of mealplanner/ already trusts: per-serving
nutrition (nutrition_scope.serving_nutrient), raw-ingredient demand
(material_accounting.candidate_input_requirements), exclusions and meal-type tags
(candidates.py), stock pools and lots (reservation.stock_pools). No second way of
computing any of them is introduced, and the solver never touches Structr.

The slots are an INPUT: a call-time template of (start, meal type), not stored
data (Sec 4.2). Entries already in the MealPlan become fixed slots the planner
respects and cannot change.

What is left out is recorded in `problem.notes` rather than dropped silently: a
recipe with no yield stated in servings, an entry with no start time, a target
that cannot be evaluated at its scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mealplanner.candidates import (
    active_nutrition_targets, candidate_consumed_types, candidate_meal_types, excluded_domain_type_ids, soft_exclusions,
)
from mealplanner.inventory import shelf_life_days
from mealplanner.material_accounting import candidate_input_requirements, recipe_servings_strict
from mealplanner.nutrition_scope import (
    active_entries, entry_servings_eaten, entry_start, serving_nutrient, target_scope_problem,
)
from mealplanner.planning.model import Candidate, Fixed, Lot, PlanningProblem, Slot, Target, Weights
from mealplanner.reservation import stock_pools
from mealplanner.scoring import number
from mealplanner.typetree import dt
from structr_client import ReadCache

LEFTOVER_CLASS = "Cooked Leftover"


@dataclass(frozen=True)
class SlotSpec:
    """One slot to fill: when it starts and what meal it is. `key` names it in
    reports and in the entries created for it (no commas or semicolons)."""

    start: datetime
    meal_type: str | None = None
    key: str | None = None

    def label(self) -> str:
        return self.key or (self.start.strftime("%a %d %b %H:%M") + (f" {self.meal_type}" if self.meal_type else ""))


def _leftover_days(client, override: float | None) -> float | None:
    if override is not None:
        return override
    try:
        return shelf_life_days(client, dt(client, LEFTOVER_CLASS), "Sealed", "Fridge")
    except LookupError:
        return None


def build_problem(
    client, meal_plan_id: str, template, now: datetime, *,
    servings_eaten: float = 1.0, max_difficulty: str | None = None, leftover_days: float | None = None,
    leftovers: bool = True,
) -> PlanningProblem:
    """Read the MealPlan, the recipes, the stock and the constraints into a
    PlanningProblem for the slots in `template` (an iterable of SlotSpec).

    leftover_days: how long cooked food keeps. Defaults to the ShelfLife default of
    the "Cooked Leftover" class (Fridge, Sealed); if none resolves, leftovers are
    simply not planned. leftovers=False plans no leftovers at all."""
    client = ReadCache(client)
    notes: list[str] = []
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    weights = Weights(
        time=number(meal_plan.get("timeBudgetWeight"), 0.5), variety=number(meal_plan.get("varietyWeight"), 0.5),
        stock=number(meal_plan.get("stockWeight"), 0.0), waste=number(meal_plan.get("wasteWeight"), 0.0),
        time_budget_minutes=number(meal_plan.get("timeBudgetMinutes"), 60.0),
    )

    targets = []
    for raw in active_nutrition_targets(client, meal_plan):
        nutrient, range_ref = raw.get("forNutrient"), raw.get("hasTargetRange")
        if not nutrient or not range_ref:
            notes.append(f"target {raw.get('name')!r} has no nutrient or range and is ignored")
            continue
        rng = client.get_all("QuantitySpecification", range_ref["id"])["result"]
        problem_text = target_scope_problem(raw, rng.get("unit"))
        if problem_text:
            notes.append(f"target {raw.get('name')!r} is not evaluated: {problem_text}")
            continue
        targets.append(Target(
            name=raw["name"], nutrient=nutrient["id"], scope=raw["hasTimeScope"], minimum=rng.get("minValue"),
            maximum=rng.get("maxValue"), hard=raw.get("strictness") == "hard", weight=number(raw.get("weight"), 0.0),
            nutrient_name=nutrient["name"],
        ))

    # Entries already in the MealPlan: fixed slots. A leftover entry is kept only if
    # its source is another kept entry that starts earlier (a chain is resolved by
    # repeating until nothing more is dropped); anything else cannot be placed.
    placed: dict[str, tuple] = {}
    for entry in active_entries(client, meal_plan):
        start = entry_start(client, entry)
        if start is None:
            notes.append(f"entry {entry['name']!r} has no start time and cannot be placed")
        else:
            placed[entry["id"]] = (start, entry)
    dropped = True
    while dropped:
        dropped = False
        for entry_id, (start, entry) in list(placed.items()):
            if entry.get("references"):
                continue
            source = (entry.get("consumesLeftoverFrom") or {}).get("id")
            if source not in placed or placed[source][0] >= start:
                notes.append(f"entry {entry['name']!r} takes leftovers from an entry that is not earlier in this plan and is ignored")
                del placed[entry_id]
                dropped = True

    # Order everything by start; at equal starts the fixed entries come first.
    rows: list[tuple] = [(start, 0, "fixed", entry) for start, entry in placed.values()]
    for spec in template:
        rows.append((spec.start, 1, "open", spec))
    rows.sort(key=lambda row: (row[0], row[1]))
    index_of_entry = {row[3]["id"]: i for i, row in enumerate(rows) if row[2] == "fixed"}

    forced: set[str] = set()         # plans a fixed entry cooks: they must be candidates whatever else is true
    for _, _, kind, payload in rows:
        if kind == "fixed" and payload.get("references"):
            forced.add(payload["references"]["id"])

    excluded = excluded_domain_type_ids(client)
    soft = soft_exclusions(client)
    keep_days = _leftover_days(client, leftover_days) if leftovers else None

    raw_plans: list[tuple[dict, list]] = []
    for plan in client.get_all("Plan")["result"]:
        recipe_ref = plan.get("specializationOf")
        retired = bool(recipe_ref and client.get_all("RecipeIdentity", recipe_ref["id"])["result"].get("isRetired"))
        if retired and plan["id"] not in forced:
            continue
        raw_plans.append((plan, candidate_input_requirements(client, plan)))
    pool_of, lots_by_pool = stock_pools(client, {t for _, reqs in raw_plans for t, _ in reqs}, now)

    candidates: dict[str, Candidate] = {}
    for plan, requirements in raw_plans:
        servings = recipe_servings_strict(client, plan)
        if servings is None:
            if plan["id"] not in forced:
                notes.append(f"recipe {plan['name']!r} is left out: no yield stated in servings")
                continue
            notes.append(f"recipe {plan['name']!r} has no yield in servings; its fixed entry is kept but uses no stock")
            servings, requirements = 1.0, []
        nutrients, untrusted = {}, set()
        for target in targets:
            amount, trusted = serving_nutrient(client, plan, target.nutrient)
            nutrients[target.nutrient] = amount
            if amount is not None and not trusted:
                untrusted.add(target.nutrient)
        demand: dict[str, float] = {}
        for type_id, grams in requirements:
            demand[pool_of[type_id]] = demand.get(pool_of[type_id], 0.0) + grams
        consumed = candidate_consumed_types(client, plan)
        uses = []
        for ref in plan.get("referencedByEntries", []):
            entry = client.get_all("MealPlanEntry", ref["id"])["result"]
            if entry.get("isSkipped") or (entry.get("memberOf") or {}).get("id") == meal_plan_id:
                continue
            used = entry_start(client, entry)
            if used is not None:
                uses.append(used)
        candidates[plan["id"]] = Candidate(
            id=plan["id"], name=plan["name"], meal_types=frozenset(candidate_meal_types(client, plan)),
            minutes=plan.get("estimatedDurationMinutes"), difficulty=plan.get("difficultyRating"),
            yield_servings=servings, nutrients=nutrients, untrusted=frozenset(untrusted), demand=demand,
            hard_excluded=bool(consumed & excluded),
            soft_penalty=sum(weight for _, weight, banned in soft if consumed & banned),
            leftover_days=keep_days, uses=tuple(sorted(uses)),
        )

    slots: list[Slot] = []
    for start, _, kind, payload in rows:
        if kind == "open":
            slots.append(Slot(payload.label(), start, payload.meal_type))
            continue
        eaten, _ = entry_servings_eaten(client, payload)
        if payload.get("references"):
            fixed = Fixed(eaten=eaten, candidate=payload["references"]["id"], cooked=payload.get("hasPlannedServings"),
                          name=payload["name"], entry_id=payload["id"])
        else:
            fixed = Fixed(eaten=eaten, source=index_of_entry[payload["consumesLeftoverFrom"]["id"]],
                          name=payload["name"], entry_id=payload["id"])
        slots.append(Slot(payload["name"], start, None, fixed))

    lots = tuple(
        Lot(pool=root, grams=lot.grams, expires=lot.expires, name=lot.name)
        for root, pool_lots in lots_by_pool.items() for lot in pool_lots
    )
    return PlanningProblem(
        slots=tuple(slots), candidates=candidates, targets=tuple(targets), lots=lots, weights=weights, now=now,
        max_difficulty=max_difficulty, servings_eaten=servings_eaten, notes=notes,
    )
