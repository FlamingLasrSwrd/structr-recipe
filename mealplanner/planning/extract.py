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

A MealPlan for a household (MealPlan.forHousehold, data-model.md Sec 19) feeds its
members: they are the problem's eaters, each target is its person's, each person's
baseline is their own, and a committed entry's meal shares say who ate what.
Without a household there is one unnamed eater, as before households.
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
    active_entries, baseline_day_intake, baseline_plans, convert_nutrient, entry_servings_eaten, entry_start,
    serving_nutrient_figure, target_scope_problem,
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
    eaters: tuple | None = None      # the names of who eats it; None: the whole household

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
    leftovers: bool = True, portions: tuple = (), eater_portions: dict | None = None,
) -> PlanningProblem:
    """Read the MealPlan, the recipes, the stock and the constraints into a
    PlanningProblem for the slots in `template` (an iterable of SlotSpec).

    leftover_days: how long cooked food keeps. Defaults to the ShelfLife default of
    the "Cooked Leftover" class (Fridge, Sealed); if none resolves, leftovers are
    simply not planned. leftovers=False plans no leftovers at all. eater_portions:
    a person's own portion levels, by name."""
    client = ReadCache(client)
    notes: list[str] = []
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    people = _household(client, meal_plan)                       # person id -> Person, in name order
    id_of = {p["name"]: pid for pid, p in people.items()}
    weights = Weights(
        time=number(meal_plan.get("timeBudgetWeight"), 0.5), variety=number(meal_plan.get("varietyWeight"), 0.5),
        stock=number(meal_plan.get("stockWeight"), 0.0), waste=number(meal_plan.get("wasteWeight"), 0.0),
        time_budget_minutes=number(meal_plan.get("timeBudgetMinutes"), 60.0),
    )

    # Every figure for one nutrient is read in one unit, the unit of the first target
    # on it; a later target on the same nutrient in another unit of the same dimension
    # has its range converted to that unit (J17).
    targets, unit_of, name_of = [], {}, {}
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
        unit = unit_of.setdefault(nutrient["id"], rng["unit"])
        name_of[nutrient["id"]] = nutrient["name"]
        factor = convert_nutrient(1.0, rng["unit"], unit)
        if factor is None:
            notes.append(f"target {raw.get('name')!r} is not evaluated: its unit {rng['unit']!r} does not convert to "
                         f"{unit!r}, the unit of another target on {nutrient['name']}")
            continue
        scaled = [None if v is None else v * factor for v in (rng.get("minValue"), rng.get("maxValue"))]
        eater = ""
        if people:
            eater = (raw.get("forPerson") or {}).get("id") or ""
            if eater not in people:
                notes.append(f"target {raw.get('name')!r} is not evaluated: it is for no one in the household")
                continue
        targets.append(Target(
            name=raw["name"], nutrient=nutrient["id"], scope=raw["hasTimeScope"], minimum=scaled[0],
            maximum=scaled[1], hard=raw.get("strictness") == "hard", weight=number(raw.get("weight"), 0.0),
            nutrient_name=nutrient["name"], day_boundary=raw.get("dayBoundaryRule") or "midnight", eater=eater,
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
    if leftovers and keep_days is None:
        notes.append("leftovers are not planned: no keeping time for cooked food resolves "
                     f"(a ShelfLife default for {LEFTOVER_CLASS!r}, or leftover_days)")

    raw_plans: list[tuple[dict, list]] = []
    baseline_ids = {ref["id"] for ref in meal_plan.get("hasBaseline", [])}
    for person in people.values():
        baseline_ids |= {ref["id"] for ref in person.get("hasBaseline", [])}
    for plan in client.get_all("Plan")["result"]:
        if plan["id"] in baseline_ids:
            continue                          # eaten every day already, not a meal to plan
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
        nutrients, untrusted, estimated = {}, set(), set()
        for nutrient_id, unit in unit_of.items():
            figure = serving_nutrient_figure(client, plan, nutrient_id, unit)
            nutrients[nutrient_id] = figure.amount
            if figure.amount is not None and not figure.trusted:
                untrusted.add(nutrient_id)
            elif figure.amount is not None and figure.estimated:
                estimated.add(nutrient_id)
        if estimated == {n for n, amount in nutrients.items() if amount is not None}:
            notes.append(f"recipe {plan['name']!r}: all its figures rest on estimates (J21)")
        elif estimated:
            notes.append(f"recipe {plan['name']!r}: its {', '.join(sorted(name_of[n] for n in estimated))} "
                         f"figure(s) rest on estimates (J21)")
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
            eaters = None
            if payload.eaters is not None:
                unknown = [name for name in payload.eaters if name not in id_of]
                if unknown or not people:
                    raise ValueError(f"{payload.label()}: {unknown or list(payload.eaters)} are not in the week's household")
                eaters = tuple(id_of[name] for name in payload.eaters)
            slots.append(Slot(payload.label(), start, payload.meal_type, eaters=eaters))
            continue
        eaten, _ = entry_servings_eaten(client, payload)
        shares = _entry_shares(client, payload, people) if people else ()
        if people and not shares:
            first = next(iter(people.values()))["name"]
            notes.append(f"entry {payload['name']!r} says nothing of who ate it: counted as {first}'s")
        common = dict(name=payload["name"], entry_id=payload["id"], shares=shares)
        if payload.get("references"):
            fixed = Fixed(eaten=eaten, candidate=payload["references"]["id"], cooked=payload.get("hasPlannedServings"), **common)
        else:
            fixed = Fixed(eaten=eaten, source=index_of_entry[payload["consumesLeftoverFrom"]["id"]], **common)
        slots.append(Slot(payload["name"], start, None, fixed, eaters=tuple(e for e, _ in shares) or None))

    baseline: dict[str, float | None] = {}
    if baseline_ids:
        for nutrient_id, unit in unit_of.items():
            per_day, unknown = baseline_day_intake(client, meal_plan, nutrient_id, unit)
            baseline[nutrient_id] = None if unknown else per_day
        names = sorted(p["name"] for p in baseline_plans(client, meal_plan))
        notes.append(f"baseline counted every day: {', '.join(names)} ("
                     + "; ".join(f"{name_of[n]} {'unknown' if v is None else f'{v:g} {unit_of[n]}'}"
                                 for n, v in sorted(baseline.items(), key=lambda kv: name_of[kv[0]])) + ")")
    baselines: dict[str, dict] = {}
    for pid, person in people.items():
        if not person.get("hasBaseline"):
            continue
        mine = {}
        for nutrient_id, unit in unit_of.items():
            per_day, unknown = baseline_day_intake(client, person, nutrient_id, unit)
            mine[nutrient_id] = None if unknown else per_day
        baselines[pid] = mine
        names = sorted(p["name"] for p in baseline_plans(client, person))
        notes.append(f"{person['name']}'s baseline counted every day: {', '.join(names)}")
    unknown = sorted(set(eater_portions or {}) - set(id_of))
    if unknown:
        raise ValueError(f"portions are given for {unknown}, who are not in the week's household")
    lots = tuple(
        Lot(pool=root, grams=lot.grams, expires=lot.expires, name=lot.name)
        for root, pool_lots in lots_by_pool.items() for lot in pool_lots
    )
    return PlanningProblem(
        slots=tuple(slots), candidates=candidates, targets=tuple(targets), lots=lots, weights=weights, now=now,
        max_difficulty=max_difficulty, servings_eaten=servings_eaten, notes=notes, baseline=baseline, units=dict(unit_of),
        portions=tuple(portions), eaters=tuple(people), baselines=baselines,
        eater_portions={id_of[name]: tuple(levels) for name, levels in (eater_portions or {}).items()},
        eater_names={pid: p["name"] for pid, p in people.items()},
    )


def _household(client, meal_plan: dict) -> dict:
    """The week's household members (Person id -> Person), in name order; empty without a household."""
    ref = meal_plan.get("forHousehold")
    if not ref:
        return {}
    members = client.get_all("Household", ref["id"])["result"].get("members", [])
    people = [client.get_all("Person", m["id"])["result"] for m in members]
    return {p["id"]: p for p in sorted(people, key=lambda p: (p["name"], p["id"]))}


def _entry_shares(client, entry: dict, people: dict) -> tuple:
    """((person id, servings), ...) from an entry's meal shares (Sec 19 K3), in the household's order."""
    shares = {}
    for ref in entry.get("hasShare", []):
        share = client.get_all("MealShare", ref["id"])["result"]
        eater = (share.get("eatenBy") or {}).get("id")
        servings, _ = entry_servings_eaten(client, share)
        if eater in people:
            shares[eater] = shares.get(eater, 0.0) + servings
    return tuple((pid, shares[pid]) for pid in people if pid in shares)
