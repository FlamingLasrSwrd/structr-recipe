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
    x the recipe's output mass / its yield in servings; or, when the dish
    has no profile of its own, the sum over its ingredients (rule 7(b),
    serving_nutrient_figure). A leftover-consuming entry
    (consumesLeftoverFrom) takes its food from the source entry's recipe,
    followed up to MAX_LEFTOVER_HOPS.
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
            target's dayBoundaryRule: "midnight" is midnight UTC, and
            "midnight America/Denver" (any IANA zone) the owner's local
            midnight. Any other rule is reported as unsupported, never
            guessed (invariant 30 requires the rule to be stated).
  weekly    every active entry of the MealPlan. A MealPlan is one week
            by construction, so plan membership is the week boundary.
Skipped entries never count. Fulfilled (already cooked) entries DO count:
they were eaten, unlike reservation where a fulfilled entry's stock is
already gone from inventory.

Units (J17). A NutrientProfile states the unit of its amount (g, mg, ug,
kcal, kJ or IU). Every figure is asked for in a unit, normally the unit of
the target's range, and converted within its dimension (mass, energy, or
IU, which is nutrient-specific and never converts to a mass); a figure in
another dimension is unknown for that question. A profile with no unit or
an unrecognised one raises NutrientUnitError: it used to be grams by
convention, and a bad record should be visibly broken, not quietly wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mealplanner.defaults import resolve_default
from mealplanner.material_accounting import candidate_outputs, recipe_servings_strict
from mealplanner.unit_conversion import QuantityError, convert_to_grams
from structr_client import ReadCache

FMT = "%Y-%m-%dT%H:%M:%S%z"
DEFAULT_SERVINGS_EATEN = 1.0
SUPPORTED_DAY_BOUNDARY = "midnight"
MAX_LEFTOVER_HOPS = 5
RETENTION_KIND = "RetentionFactor"

# unit (lowercased) -> (dimension, factor to the dimension's base unit: g, kcal, IU).
# 1 kcal = 4.184 kJ, the thermochemical calorie FoodData Central uses.
NUTRIENT_UNITS: dict[str, tuple[str, float]] = {
    "g": ("mass", 1.0),
    "mg": ("mass", 1e-3),
    "ug": ("mass", 1e-6),
    "µg": ("mass", 1e-6),
    "kcal": ("energy", 1.0),
    "kj": ("energy", 1.0 / 4.184),
    "iu": ("iu", 1.0),
}


class NutrientUnitError(QuantityError):
    """A nutrient amount whose unit is missing or not one of NUTRIENT_UNITS."""


class AmbiguousProfileError(RuntimeError):
    """One Type with two per-100 g profiles for the same nutrient."""


def nutrient_unit(unit: str | None, what: str = "nutrient amount") -> tuple[str, float]:
    """(dimension, factor to its base unit) for a nutrient unit, or NutrientUnitError."""
    entry = NUTRIENT_UNITS.get(unit.strip().lower()) if isinstance(unit, str) else None
    if entry is None:
        raise NutrientUnitError(f"{what}: unit {unit!r} is not a nutrient unit ({', '.join(NUTRIENT_UNITS)})")
    return entry


def convert_nutrient(amount: float, from_unit: str, to_unit: str) -> float | None:
    """`amount` in from_unit expressed in to_unit, or None if the two are
    different dimensions (grams cannot become kcal or IU)."""
    from_dim, from_factor = nutrient_unit(from_unit)
    to_dim, to_factor = nutrient_unit(to_unit)
    if from_dim != to_dim:
        return None
    return amount * from_factor / to_factor


@dataclass(frozen=True)
class ProfileFigure:
    amount: float              # per 100 g, or per unit for a per_unit profile, in `unit`
    unit: str
    provenance: str | None     # "placeholder", "sourced", "estimated", "calculated", or None if never set


def profile_figure(client, type_id: str, nutrient_id: str, basis: str = "per_100g") -> ProfileFigure | None:
    """A Type's OWN NutrientProfile for this nutrient on `basis` ("per_100g", or
    "per_unit" for a food counted in units, as a supplement's label is), or None
    if it has none. Profiles are not inherited down the hierarchy: a parent's
    figure is not a measurement of its child. Two profiles for one nutrient and
    basis on one Type raise rather than one being picked."""
    node = client.get_all("DomainType", type_id)["result"]
    found = []
    for profile_ref in node.get("nutrientProfilesAbout", []):
        profile = client.get_all("NutrientProfile", profile_ref["id"])["result"]
        if (profile.get("forNutrient") or {}).get("id") == nutrient_id and profile.get("basis") == basis:
            found.append(profile)
    if not found:
        return None
    if len(found) > 1:
        raise AmbiguousProfileError(f"{node.get('name')!r} has {len(found)} {basis} profiles for one nutrient: "
                                    f"{sorted(p['name'] for p in found)}")
    profile = found[0]
    if profile.get("amount") is None:
        return None
    nutrient_unit(profile.get("unit"), f"NutrientProfile {profile['name']!r}")
    return ProfileFigure(profile["amount"], profile["unit"], profile.get("provenance"))


def nutrient_profile_record(client, output_type_id: str, nutrient_id: str) -> tuple[float | None, str | None]:
    """(per-100 g amount in the profile's own unit, provenance), or (None, None)
    if the Type has no per-100 g profile for this nutrient (profile_figure)."""
    figure = profile_figure(client, output_type_id, nutrient_id)
    return (None, None) if figure is None else (figure.amount, figure.provenance)


def nutrient_profile_amount(client, output_type_id: str, nutrient_id: str) -> float | None:
    """Per-100g amount from the output type's own NutrientProfile for this
    nutrient, or None (see nutrient_profile_record)."""
    return nutrient_profile_record(client, output_type_id, nutrient_id)[0]


@dataclass(frozen=True)
class ServingFigure:
    """One serving's worth of a nutrient, and how it was established."""

    amount: float | None           # in the unit asked for; None if unknown
    trusted: bool                  # may a hard target be decided on it (J15, J21)
    method: str | None = None      # "dish" (rule 7(a)) or "ingredients" (rule 7(b))
    reason: str | None = None      # why it is unknown, untrusted or estimated
    unadjusted: tuple[str, ...] = ()   # ingredients no retention factor resolved for
    estimated: bool = False        # usable, but rests on an estimate somewhere (J21)


def _unknown(reason: str, method: str | None = None) -> ServingFigure:
    return ServingFigure(None, False, method, reason)


def serving_nutrient_figure(client, plan: dict, nutrient_id: str, unit: str = "g") -> ServingFigure:
    """The nutrient in ONE serving of a Plan's output, in `unit`.

    Rule 7(a), the dish's own profiles: used when every final output
    (material_accounting.candidate_outputs) has a per-100 g profile for this
    nutrient AND a mass, and the Plan's amount is the sum over all of them.

    Rule 7(b), from the ingredients: otherwise, when the Plan has exactly one
    final output, it is the sum over the raw, non-optional inputs of
    grams x per-100 g x retention factor, divided by the servings
    (_from_ingredients). With several final outputs and no profiles of their
    own, which ingredients went into which output is not modeled, so the answer
    is unknown.

    Unknown propagates: a missing piece makes the whole figure None rather than
    a partial sum. A figure is trusted (usable for a hard target) when every
    profile behind it is sourced, estimated or calculated (J21, the owner's
    decision: a placeholder or unmarked profile is not); it is `estimated` when
    any of them is not sourced or, from ingredients, an ingredient had no
    retention factor."""
    outputs = candidate_outputs(client, plan)
    if not outputs:
        return _unknown("the recipe has no final output")
    servings = recipe_servings_strict(client, plan)
    if servings is None:
        return _unknown("the recipe's yield is not stated in servings")
    figures = [profile_figure(client, type_id, nutrient_id) for type_id, _ in outputs]
    if all(f is not None for f in figures) and all(grams is not None for _, grams in outputs):
        total, provenances = 0.0, set()
        for (_, grams), figure in zip(outputs, figures):
            per_100g = convert_nutrient(figure.amount, figure.unit, unit)
            if per_100g is None:
                return _unknown(f"the dish's profile is in {figure.unit}, not comparable with {unit}", "dish")
            provenances.add(figure.provenance)
            total += grams * per_100g / 100.0
        trusted, estimated, reason = _judge(provenances, [])
        return ServingFigure(total / servings, trusted, "dish", reason, (), estimated)
    if len(outputs) != 1:
        return _unknown("several final outputs without profiles of their own: which ingredients went into "
                        "which is not modeled")
    return _from_ingredients(client, plan, nutrient_id, unit, servings)


COUNT_UNITS = frozenset({"each", "count", "whole"})


def _input_count(client, spec: dict) -> float | None:
    """How many units a Specification calls for, if its quantity is a count."""
    qty_ref = spec.get("hasSpecifiedQuantity")
    if not qty_ref:
        return None
    qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
    return qty.get("value") if qty.get("unit") in COUNT_UNITS else None


def _input_grams(client, spec: dict, type_id: str) -> float | None:
    qty_ref = spec.get("hasSpecifiedQuantity")
    if not qty_ref:
        return None
    qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
    if qty.get("value") is None:
        return None
    return convert_to_grams(client, type_id, qty["value"], qty.get("unit"))


def _retention_kind(client) -> str | None:
    matches = client.get("/structr/rest/DomainType", params={"name": RETENTION_KIND})["result"]
    if len(matches) > 1:
        raise LookupError(f"expected at most one DomainType named {RETENTION_KIND!r}, found {len(matches)}")
    return matches[0]["id"] if matches else None


def retention_factor(client, type_id: str, method_id: str | None, nutrient_id: str) -> float | None:
    """The share of this nutrient left in this food after this transformation:
    a RetentionFactor default (Sec 8) keyed by the nutrient and, optionally, the
    transformation, resolved up the food's hierarchy like any default. None if
    none resolves. One not keyed by the nutrient, or not a ratio, is malformed
    and raises."""
    kind_id = _retention_kind(client)
    if kind_id is None:
        return None
    keys = {nutrient_id} | ({method_id} if method_id else set())
    resolved = resolve_default(client, type_id, kind_id, keys)
    if resolved is None:
        return None
    value, unit = resolved.quantity.get("value"), resolved.quantity.get("unit")
    if nutrient_id not in resolved.keyed_by or unit != "ratio" or value is None or value < 0:
        raise ValueError(f"RetentionFactor {resolved.default_name!r} must be keyed by its nutrient and be a "
                         f"non-negative ratio; got {value!r} {unit!r}")
    return value


def _from_ingredients(client, plan: dict, nutrient_id: str, unit: str, servings: float) -> ServingFigure:
    """Rule 7(b). The dish holds what its ingredients held, less what cooking
    destroys: water loss changes a figure per 100 g, not per serving, so no
    yield factor is needed for an amount per serving. Each ingredient's share is
    multiplied by its retention factor for the Step that takes it; where none
    resolves it is counted whole and named in `unadjusted`, which makes the
    figure an estimate (an upper bound for a nutrient that cooking destroys).

    Only RAW inputs count (a type no Step of the Plan produces, J5), so an
    intermediate is not counted twice, and an intermediate's own profile is not
    used. Optional inputs are left out: the dish is complete without them. An
    ingredient with no stated or convertible quantity makes the figure unknown,
    unless its profile says it has none of this nutrient; such an ingredient
    needs no quantity and no retention factor, since none stays none."""
    steps = [client.get_all("Step", ref["id"])["result"] for ref in plan.get("steps", [])]
    specs_by_step = [
        (step, [client.get_all("Specification", ref["id"])["result"] for ref in step.get("hasSpecification", [])])
        for step in steps
    ]
    produced = {
        s["specifies"]["id"] for _, specs in specs_by_step for s in specs
        if s.get("hasParticipationRole") == "output" and s.get("specifies")
    }
    total, provenances, unadjusted, counted = 0.0, set(), [], 0
    for step, specs in specs_by_step:
        method_id = (step.get("instanceOf") or {}).get("id")
        for spec in specs:
            specifies = spec.get("specifies")
            if spec.get("hasParticipationRole") != "input" or not specifies or specifies["id"] in produced:
                continue
            if spec.get("isOptional"):
                continue
            counted += 1
            name = specifies.get("name") or specifies["id"]
            figure = profile_figure(client, specifies["id"], nutrient_id)
            per_unit = figure is None
            if per_unit:
                figure = profile_figure(client, specifies["id"], nutrient_id, basis="per_unit")
            if figure is None:
                return _unknown(f"ingredient {name!r} has no profile for this nutrient", "ingredients")
            per_basis = convert_nutrient(figure.amount, figure.unit, unit)
            if per_basis is None:
                return _unknown(f"ingredient {name!r}'s profile is in {figure.unit}, not comparable with {unit}",
                                "ingredients")
            provenances.add(figure.provenance)
            if per_basis == 0:
                continue          # none of it, whatever the quantity or the cooking
            if per_unit:
                units = _input_count(client, spec)
                if units is None:
                    return _unknown(f"ingredient {name!r} is labelled per unit, so it needs a count", "ingredients")
                amount = units * per_basis
            else:
                grams = _input_grams(client, spec, specifies["id"])
                if grams is None:
                    return _unknown(f"ingredient {name!r} has no quantity that converts to grams", "ingredients")
                amount = grams * per_basis / 100.0
            factor = retention_factor(client, specifies["id"], method_id, nutrient_id)
            if factor is None:
                factor = 1.0
                if name not in unadjusted:        # an ingredient used in two Steps is named once
                    unadjusted.append(name)
            total += amount * factor
    if counted == 0:
        return _unknown("the recipe lists no ingredients", "ingredients")
    trusted, estimated, reason = _judge(provenances, unadjusted)
    return ServingFigure(total / servings, trusted, "ingredients", reason, tuple(unadjusted), estimated)


USABLE = frozenset({"sourced", "estimated", "calculated"})


def _judge(provenances: set, unadjusted: list[str]) -> tuple[bool, bool, str | None]:
    """(trusted, estimated, reason) for a figure built on profiles of these
    provenances. J21, the owner's decision: an estimate is good enough to plan
    with (calorie figures are +-30% anyway) and is reported as one; a placeholder
    or a profile of unknown origin is not."""
    if not provenances <= USABLE:
        return False, False, "a profile is placeholder or unmarked"
    estimated = bool(provenances - {"sourced"}) or bool(unadjusted)
    notes = []
    if provenances - {"sourced"}:
        notes.append("a profile is " + " or ".join(sorted(provenances - {"sourced"})))
    if unadjusted:
        notes.append(f"no retention factor for {', '.join(unadjusted)}")
    return True, estimated, "; ".join(notes) or None


def serving_nutrient(client, plan: dict, nutrient_id: str, unit: str = "g") -> tuple[float | None, bool]:
    """(the nutrient in ONE serving of a Plan's output, in `unit`, or None if it
    can't be established; whether it is trusted). See serving_nutrient_figure.

    The second value is what the planner uses to keep a hard target from being
    decided on placeholder data (J15) or on a figure not adjusted for cooking
    losses (J18)."""
    figure = serving_nutrient_figure(client, plan, nutrient_id, unit)
    return figure.amount, figure.trusted


def serving_nutrient_amount(client, plan: dict, nutrient_id: str, unit: str = "g") -> float | None:
    """The nutrient in ONE serving of a Plan's output, in `unit`, or None if it
    can't be established (see serving_nutrient_figure)."""
    return serving_nutrient(client, plan, nutrient_id, unit)[0]


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


def entry_nutrient_intake(client, entry: dict, nutrient_id: str, unit: str = "g") -> tuple[float | None, bool]:
    """(the nutrient eaten at this entry, in `unit`, or None if unknown,
    whether the default servings was assumed)."""
    plan = _source_plan(client, entry)
    if plan is None:
        return None, False
    per_serving = serving_nutrient_amount(client, plan, nutrient_id, unit)
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


@lru_cache(maxsize=None)
def day_zone(rule: str | None) -> tzinfo | None:
    """The zone whose midnight a dayBoundaryRule names, or None for a rule that
    is not supported: "midnight" is UTC, "midnight <IANA zone>" that zone. With
    UTC, a 18:30 dinner in Denver (00:30 UTC) counted toward the next day."""
    if rule == SUPPORTED_DAY_BOUNDARY:
        return timezone.utc
    if isinstance(rule, str) and rule.startswith(SUPPORTED_DAY_BOUNDARY + " "):
        try:
            return ZoneInfo(rule[len(SUPPORTED_DAY_BOUNDARY) + 1:])
        except (ZoneInfoNotFoundError, ValueError):
            return None
    return None


def calendar_day(when: datetime, zone: tzinfo = timezone.utc) -> date:
    return when.astimezone(zone).date()


@dataclass
class ScopeTotal:
    """A scoped nutrient total. `total` covers only entries whose intake
    is known, so it is a lower bound whenever `unknown` is non-empty."""
    total: float = 0.0
    counted: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    assumed_default_servings: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    baseline: float = 0.0          # the part of `total` the MealPlan's baseline adds


def active_entries(client, meal_plan: dict) -> list[dict]:
    entries = [client.get_all("MealPlanEntry", ref["id"])["result"] for ref in meal_plan.get("hasEntry", [])]
    return [e for e in entries if not e.get("isSkipped")]


def baseline_plans(client, meal_plan: dict) -> list[dict]:
    """The Plans a MealPlan counts as eaten every day, outside its planned meals:
    supplements, the morning coffee (MealPlan.hasBaseline, data-model J25)."""
    return [client.get_all("Plan", ref["id"])["result"] for ref in meal_plan.get("hasBaseline", [])]


def baseline_day_intake(client, meal_plan: dict, nutrient_id: str, unit: str = "g") -> tuple[float, list[str]]:
    """What the baseline adds to each day, in `unit`: one serving of every baseline
    Plan, a serving of one being a day of it. Also the names of any baseline Plan
    with no figure for the nutrient, which leave the day's total unknown."""
    total, unknown = 0.0, []
    for plan in baseline_plans(client, meal_plan):
        amount = serving_nutrient_figure(client, plan, nutrient_id, unit).amount
        if amount is None:
            unknown.append(plan["name"])
        else:
            total += amount
    return total, unknown


def scope_total(
    client, meal_plan: dict, nutrient_id: str, scope: str, when: datetime | None = None, unit: str = "g",
    zone: tzinfo = timezone.utc,
) -> ScopeTotal:
    """Nutrient already planned inside one scope of a MealPlan, in `unit`.

    scope "weekly": every active entry. scope "daily": entries on the
    same calendar day as `when` (required); entries with no start time
    can't be placed in a day and are listed as `unplaced`. The baseline is
    added once for each day in the scope: the day of `when`, and for a week
    every day holding an entry as well."""
    result = ScopeTotal()
    if scope == "daily" and when is None:
        raise ValueError("scope_total(scope='daily') needs `when`")
    days = {calendar_day(when, zone)} if when is not None else set()
    for entry in active_entries(client, meal_plan):
        start = entry_start(client, entry)
        if scope == "daily":
            if start is None:
                result.unplaced.append(entry["name"])
                continue
            if calendar_day(start, zone) != calendar_day(when, zone):
                continue
        elif start is not None:
            days.add(calendar_day(start, zone))
        intake, assumed = entry_nutrient_intake(client, entry, nutrient_id, unit)
        if intake is None:
            result.unknown.append(entry["name"])
            continue
        result.total += intake
        result.counted.append(entry["name"])
        if assumed:
            result.assumed_default_servings.append(entry["name"])
    if meal_plan.get("hasBaseline"):
        per_day, unknown = baseline_day_intake(client, meal_plan, nutrient_id, unit)
        result.baseline = per_day * len(days)
        result.total += result.baseline
        result.unknown.extend(f"{name} (baseline)" for name in unknown)
    return result


def target_scope_problem(target: dict, range_unit: str | None) -> str | None:
    """Why this target can't be evaluated at its declared scope, or None
    if it can. Reported, never guessed around."""
    scope = target.get("hasTimeScope")
    if scope not in ("per_meal", "daily", "weekly"):
        return f"no usable hasTimeScope ({scope!r})"
    if scope == "daily" and day_zone(target.get("dayBoundaryRule")) is None:
        return (f"unsupported dayBoundaryRule {target.get('dayBoundaryRule')!r} "
                f"(only {SUPPORTED_DAY_BOUNDARY!r} or '{SUPPORTED_DAY_BOUNDARY} <IANA zone>')")
    if not (isinstance(range_unit, str) and range_unit.strip().lower() in NUTRIENT_UNITS):
        return f"target range unit {range_unit!r} isn't a nutrient unit ({', '.join(NUTRIENT_UNITS)})"
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
    concluded). Totals cover the planned meals and the baseline (a day's worth
    for each day judged, none for a single meal)."""
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
                "strictness": target.get("strictness"), "min": min_val, "max": max_val, "unit": rng.get("unit")}
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
                key = calendar_day(start, day_zone(target.get("dayBoundaryRule")) or timezone.utc).isoformat()
            groups.setdefault(key, []).append(entry)

        per_day, baseline_unknown = (baseline_day_intake(client, meal_plan, nutrient["id"], rng["unit"])
                                     if meal_plan.get("hasBaseline") and scope != "per_meal" else (0.0, []))
        zone = day_zone(target.get("dayBoundaryRule")) or timezone.utc
        for key in sorted(groups):
            days = 1 if scope == "daily" else len({calendar_day(s, zone) for s in (entry_start(client, e) for e in groups[key]) if s})
            total = per_day * days if scope != "per_meal" else 0.0
            unknown = [f"{name} (baseline)" for name in baseline_unknown]
            assumed = []
            for entry in groups[key]:
                intake, was_assumed = entry_nutrient_intake(client, entry, nutrient["id"], rng["unit"])
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
