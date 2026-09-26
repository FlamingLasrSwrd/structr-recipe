"""Nutrition targets evaluated at the scope they declare.

Fixes a correctness finding from external review: the selector compared
ONE meal's per-serving nutrient amount against every NutritionTarget
regardless of NutritionTarget.hasTimeScope (daily / weekly / per_meal).
The field already existed in the schema; nothing read it. For a hard
constraint that is not a rough approximation, it produces wrong
feasibility decisions in both directions: a daily sodium cap rejects a
perfectly good meal that is one of three low-sodium meals, and a daily
protein range accepts three 61 g meals that total 183 g against an 80 g
ceiling.

What "eaten" means here. Nutrient intake at a MealPlanEntry is

    (servings eaten at that entry) x (nutrient per serving of the food)

  - servings eaten: MealPlanEntry.hasPlannedConsumption when set
    (invariant 24 makes it a quantity of the entry's own servings);
    otherwise DEFAULT_SERVINGS_EATEN. That default is a stated
    single-user convention (one person eats one serving per meal), not a
    fact about the data, so every entry that used it is reported back to
    the caller rather than absorbed silently.
  - per serving: the output type's own NutrientProfile (Sec 8 rule 7(a))
    x the recipe's output mass / its yield in servings. A leftover-
    consuming entry (consumesLeftoverFrom) takes its food from the
    source entry's recipe, followed up to MAX_LEFTOVER_HOPS.
  - unknown stays unknown: an entry with no profile, no output mass, or
    no yield in servings contributes nothing and is listed as unknown,
    so a total is either complete or explicitly a lower bound.

Why partial totals still allow one hard decision but not the other.
Nutrient amounts are never negative, so a partial total can only grow as
more meals are added. That makes a hard MAXIMUM decidable early (if the
planned meals already exceed it, no completion can fix that) and a hard
MINIMUM undecidable early (the day may simply not be filled yet). The
selector therefore disqualifies on a scoped maximum but only scores
toward a scoped minimum; nutrition_report() is where a minimum is
actually judged, once a plan is filled in.

Scope semantics:
  per_meal  one serving of the candidate against the range (the old
            behaviour, now only for targets that ask for it).
  daily     entries whose start falls on the same calendar day under the
            target's dayBoundaryRule. Only "midnight" is supported; any
            other rule is reported as unsupported, never guessed
            (invariant 30 requires the rule to be stated).
  weekly    every active entry of the MealPlan. A MealPlan is one week
            by construction, so plan membership is the week boundary.
Skipped entries never count. Fulfilled (already cooked) entries DO count:
they were eaten, unlike reservation where a fulfilled entry's stock is
already gone from inventory.

NutrientProfile has no unit field (grams per 100 g is implicit in its
basis), so a target whose range isn't stated in grams is reported as
unsupported rather than compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from mealplanner.material_accounting import candidate_outputs, recipe_servings_strict
from structr_client import ReadCache

FMT = "%Y-%m-%dT%H:%M:%S%z"
DEFAULT_SERVINGS_EATEN = 1.0
SUPPORTED_DAY_BOUNDARY = "midnight"
MAX_LEFTOVER_HOPS = 5


def nutrient_profile_record(client, output_type_id: str, nutrient_id: str) -> tuple[float | None, str | None]:
    """(per-100g amount, provenance) from the output type's own NutrientProfile
    for this nutrient (Sec 8 rule 7(a) only -- rule 7(b), deriving it from raw
    ingredients via retention factors, is not implemented). (None, None) if
    there is no per_100g profile. Provenance is "placeholder", "sourced", or
    None when it was never set."""
    output_type = client.get_all("DomainType", output_type_id)["result"]
    for profile_ref in output_type.get("nutrientProfilesAbout", []):
        profile = client.get_all("NutrientProfile", profile_ref["id"])["result"]
        if (profile.get("forNutrient") or {}).get("id") == nutrient_id and profile.get("basis") == "per_100g":
            return profile.get("amount"), profile.get("provenance")
    return None, None


def nutrient_profile_amount(client, output_type_id: str, nutrient_id: str) -> float | None:
    """Per-100g amount from the output type's own NutrientProfile for this
    nutrient, or None (see nutrient_profile_record)."""
    return nutrient_profile_record(client, output_type_id, nutrient_id)[0]


def serving_nutrient(client, plan: dict, nutrient_id: str) -> tuple[float | None, bool]:
    """(grams of the nutrient in ONE serving of a Plan's output or None if it
    can't be established, whether every profile behind that figure is
    `sourced`). The Plan's amount is the sum over EVERY final output
    (material_accounting.candidate_outputs), so a recipe with two outputs
    counts both.

    Unknown propagates: if any final output lacks a mass or a NutrientProfile
    for this nutrient, or the yield isn't stated in servings, the whole answer
    is None rather than a partial sum. That is deliberately cautious -- an
    inedible byproduct with no profile will make a recipe's nutrition unknown
    until the model can say which outputs are eaten, which it can't today.

    The second value is what the planner uses to keep a hard target from being
    decided on placeholder data: a figure counts as trusted only if every
    profile contributing to it says `sourced`, so one placeholder or unmarked
    profile makes the whole figure untrusted."""
    outputs = candidate_outputs(client, plan)
    if not outputs:
        return None, False
    servings = recipe_servings_strict(client, plan)
    if servings is None:
        return None, False
    total, trusted = 0.0, True
    for output_type_id, output_grams in outputs:
        if output_grams is None:
            return None, False
        per_100g, provenance = nutrient_profile_record(client, output_type_id, nutrient_id)
        if per_100g is None:
            return None, False
        trusted = trusted and provenance == "sourced"
        total += output_grams * per_100g / 100.0
    return total / servings, trusted


def serving_nutrient_amount(client, plan: dict, nutrient_id: str) -> float | None:
    """Grams of the nutrient in ONE serving of a Plan's output, or None if it
    can't be established (see serving_nutrient)."""
    return serving_nutrient(client, plan, nutrient_id)[0]


def _source_plan(client, entry: dict) -> dict | None:
    """The Plan whose food an entry eats: its own `references`, or for a
    leftover-consuming entry the source entry's, following the chain."""
    seen = set()
    current = entry
    for _ in range(MAX_LEFTOVER_HOPS + 1):
        if current.get("references"):
            return client.get_all("Plan", current["references"]["id"])["result"]
        source = current.get("consumesLeftoverFrom")
        if not source or source["id"] in seen:
            return None
        seen.add(source["id"])
        current = client.get_all("MealPlanEntry", source["id"])["result"]
    return None


def entry_servings_eaten(client, entry: dict) -> tuple[float, bool]:
    """(servings eaten at this entry, whether DEFAULT_SERVINGS_EATEN was
    used because hasPlannedConsumption isn't a usable servings value)."""
    ref = entry.get("hasPlannedConsumption")
    if ref:
        qty = client.get_all("QuantitySpecification", ref["id"])["result"]
        value = qty.get("value")
        if value is not None and value >= 0 and qty.get("unit") == "servings":
            return value, False
    return DEFAULT_SERVINGS_EATEN, True


def entry_nutrient_intake(client, entry: dict, nutrient_id: str) -> tuple[float | None, bool]:
    """(grams of the nutrient eaten at this entry or None if unknown,
    whether the default servings was assumed)."""
    plan = _source_plan(client, entry)
    if plan is None:
        return None, False
    per_serving = serving_nutrient_amount(client, plan, nutrient_id)
    if per_serving is None:
        return None, False
    servings, assumed = entry_servings_eaten(client, entry)
    return per_serving * servings, assumed


def entry_start(client, entry: dict) -> datetime | None:
    about = entry.get("isAbout")
    if not about:
        return None
    beginning = client.get_all("TemporalRegion", about["id"])["result"].get("hasBeginning")
    return datetime.strptime(beginning, FMT) if beginning else None


def calendar_day(when: datetime) -> date:
    return when.astimezone(timezone.utc).date()


@dataclass
class ScopeTotal:
    """A scoped nutrient total. `total` covers only entries whose intake
    is known, so it is a lower bound whenever `unknown` is non-empty."""
    total: float = 0.0
    counted: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    assumed_default_servings: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)


def active_entries(client, meal_plan: dict) -> list[dict]:
    entries = [client.get_all("MealPlanEntry", ref["id"])["result"] for ref in meal_plan.get("hasEntry", [])]
    return [e for e in entries if not e.get("isSkipped")]


def scope_total(
    client, meal_plan: dict, nutrient_id: str, scope: str, when: datetime | None = None,
) -> ScopeTotal:
    """Nutrient already planned inside one scope of a MealPlan.

    scope "weekly": every active entry. scope "daily": entries on the
    same calendar day as `when` (required); entries with no start time
    can't be placed in a day and are listed as `unplaced`."""
    result = ScopeTotal()
    if scope == "daily" and when is None:
        raise ValueError("scope_total(scope='daily') needs `when`")
    for entry in active_entries(client, meal_plan):
        if scope == "daily":
            start = entry_start(client, entry)
            if start is None:
                result.unplaced.append(entry["name"])
                continue
            if calendar_day(start) != calendar_day(when):
                continue
        intake, assumed = entry_nutrient_intake(client, entry, nutrient_id)
        if intake is None:
            result.unknown.append(entry["name"])
            continue
        result.total += intake
        result.counted.append(entry["name"])
        if assumed:
            result.assumed_default_servings.append(entry["name"])
    return result


def target_scope_problem(target: dict, range_unit: str | None) -> str | None:
    """Why this target can't be evaluated at its declared scope, or None
    if it can. Reported, never guessed around."""
    scope = target.get("hasTimeScope")
    if scope not in ("per_meal", "daily", "weekly"):
        return f"no usable hasTimeScope ({scope!r})"
    if scope == "daily" and target.get("dayBoundaryRule") != SUPPORTED_DAY_BOUNDARY:
        return f"unsupported dayBoundaryRule {target.get('dayBoundaryRule')!r} (only {SUPPORTED_DAY_BOUNDARY!r})"
    if range_unit != "g":
        return f"target range unit {range_unit!r} isn't grams (NutrientProfile amounts are grams per 100 g)"
    return None


def _status(total: float, unknown: bool, min_val: float | None, max_val: float | None) -> str:
    if max_val is not None and total > max_val:
        return "above_max"  # definite even as a lower bound: totals only grow
    if unknown:
        return "indeterminate"
    if min_val is not None and total < min_val:
        return "below_min"
    return "ok"


def nutrition_report(client, meal_plan_id: str) -> list[dict]:
    """Every attached NutritionTarget judged at its own scope over the
    plan as currently filled in. This is where a hard MINIMUM is
    actually checked, which the selector can't do mid-planning.

    One row per (target, group): per_meal -> one row per entry; daily ->
    one per calendar day that has entries; weekly -> one for the plan.
    Days with no entries aren't reported (nothing planned to judge).
    Status: ok / below_min / above_max / indeterminate (some entry has no
    nutrient data, so the total is a lower bound and a shortfall can't be
    concluded). Totals cover PLANNED meals only."""
    client = ReadCache(client)      # read-only: each node is fetched once for the whole report
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    targets = [
        client.get_all("NutritionTarget", c["id"])["result"]
        for c in meal_plan.get("hasConstraint", []) if c["type"] == "NutritionTarget"
    ]
    entries = active_entries(client, meal_plan)
    rows = []
    for target in targets:
        nutrient, range_ref = target.get("forNutrient"), target.get("hasTargetRange")
        if not nutrient or not range_ref:
            continue
        rng = client.get_all("QuantitySpecification", range_ref["id"])["result"]
        min_val, max_val = rng.get("minValue"), rng.get("maxValue")
        base = {"target": target["name"], "nutrient": nutrient["name"], "scope": target.get("hasTimeScope"),
                "strictness": target.get("strictness"), "min": min_val, "max": max_val}
        problem = target_scope_problem(target, rng.get("unit"))
        if problem:
            rows.append({**base, "group": None, "status": "unsupported", "detail": problem})
            continue

        groups: dict[str, list[dict]] = {}
        scope = target["hasTimeScope"]
        for entry in entries:
            if scope == "per_meal":
                key = entry["name"]
            elif scope == "weekly":
                key = "week"
            else:
                start = entry_start(client, entry)
                if start is None:
                    continue
                key = calendar_day(start).isoformat()
            groups.setdefault(key, []).append(entry)

        for key in sorted(groups):
            total, unknown, assumed = 0.0, [], []
            for entry in groups[key]:
                intake, was_assumed = entry_nutrient_intake(client, entry, nutrient["id"])
                if intake is None:
                    unknown.append(entry["name"])
                    continue
                total += intake
                if was_assumed:
                    assumed.append(entry["name"])
            rows.append({**base, "group": key, "total": total, "entries": len(groups[key]),
                         "unknown": unknown, "assumed_default_servings": assumed,
                         "status": _status(total, bool(unknown), min_val, max_val)})
    return rows
