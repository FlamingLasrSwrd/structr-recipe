"""The compute-don't-store inventory engine: currentMagnitude(),
physicalOnHand(), and a simplified eligibleOnHand() -- data-model.md
Sec 4.1.1 and Sec 9. Build-sketch Sec 5 places these as SchemaMethods
(currentMagnitude on Quality, physicalOnHand/eligibleOnHand on
DomainType). Implemented here as plain Python instead, matching the
selector's own precedent and for the same reason: this needs multi-hop
traversal (Quality -> bearer -> Allocations -> Process -> temporal
comparison) and date arithmetic, exactly the shape that hit
StructrScript's real ceiling building resolveDefault (step 3 --
recursive/complex multi-entity walks don't work reliably there). This
is a genuine, considered architectural choice, not a shortcut: the
"optimizer" and the inventory engine are both client-side concerns
reading/writing via REST, not stored procedures.

Sec 4.1.1's formula, implemented literally:
    current magnitude = the latest observed-or-imputed Measurement
    about a Quality, minus the summed quantities of every INPUT
    Allocation about its bearer whose Process occurred AFTER that
    Measurement's time.

Sec 9's eligibility filter is: not expired, and (when a StockPolicy's
flags are passed) passing its opened-status and storage-condition filters and
its includesSubtypes setting -- eligible_on_hand_with_urgency(). Food in no
container is outside the container-based filters (Sec 9), which round 2 #18
in REVIEW.md questions.

Invariant 15 (no more used than there was) is an audit over the same
quantities, overdraws()/find_overdraws(), not a write-time check.

Expiration is (when the food began to exist) + (the ShelfLife default for
its Perishability type, in days), per Sec 5.5. "When it began to exist" is
the start of the Process the portion `beginsToExistDuring` (a purchase, or
the cook that made a leftover), and where none is recorded, its EARLIEST
observed/imputed mass Measurement. It used to be the LATEST weighing, so
every reweighing restarted the clock and food could be kept fresh forever by
weighing it again (found by external review).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mealplanner.defaults import resolve_default
from mealplanner.typetree import ancestors_or_self, dt, subtypes_of  # noqa: F401 (re-exported)
from mealplanner.unit_conversion import QuantityError, convert_to_grams
from structr_client import ReadCache

FMT = "%Y-%m-%dT%H:%M:%S%z"


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, FMT)


def _grams(client, food_type_id: str | None, measurement: dict, what: str) -> float:
    value, unit = measurement.get("value"), measurement.get("unit")
    if value is None or not unit:
        raise QuantityError(
            f"{what} ({measurement.get('name')!r}) needs a numeric value and a unit; got {value!r} {unit!r}"
        )
    grams = convert_to_grams(client, food_type_id, value, unit)
    if grams is None:
        raise QuantityError(
            f"{what} ({measurement.get('name')!r}): {value} {unit!r} cannot be converted to grams for this food "
            f"(unrecognised unit, or it needs a Density/MassPerUnit default the food doesn't have)"
        )
    return grams


@dataclass
class Draw:
    """One input Allocation about a portion, placed in time. `grams` is None
    and `problem` says why when the quantity is unusable; the problem only
    raises if the draw falls inside a window that is actually being computed."""

    began: datetime
    grams: float | None
    label: str
    problem: str | None = None


def mass_quality(client, portion: dict) -> dict | None:
    """The portion's Mass Quality, fully loaded, or None."""
    for ref in portion.get("bearerOf", []):
        if ref["type"] != "Quality":
            continue
        quality = client.get_all("Quality", ref["id"])["result"]
        if (quality.get("hasKind") or {}).get("name") == "Mass":
            return quality
    return None


def _baselines(client, quality: dict) -> list[tuple[datetime, dict]]:
    """(time, Measurement) for every observed-or-imputed Measurement of the
    Quality that has a time, oldest first."""
    found = []
    for ref in quality.get("measurements", []):
        m = client.get_all("Measurement", ref["id"])["result"]
        if m.get("status") in ("observed", "imputed") and m.get("hasTime"):
            found.append((_parse(m["hasTime"]), m))
    return sorted(found, key=lambda pair: pair[0])


def _draws(client, bearer: dict, food_type_id: str | None) -> list[Draw]:
    """Every input Allocation about the bearer. A Process with no start time
    raises here: its consumption could not be placed against any baseline."""
    draws = []
    for alloc_ref in bearer.get("allocationsAbout", []):
        alloc = client.get_all("Allocation", alloc_ref["id"])["result"]
        if alloc.get("hasParticipationRole") != "input":
            continue
        process_ref = alloc.get("process")
        if not process_ref:
            continue
        process = client.get_all("Process", process_ref["id"])["result"]
        region_ref = process.get("occupiesTemporalRegion")
        beginning = client.get_all("TemporalRegion", region_ref["id"])["result"].get("hasBeginning") if region_ref else None
        if not beginning:
            raise QuantityError(
                f"input Allocation {alloc.get('name')!r} belongs to a Process with no start time, "
                f"so its consumption cannot be placed relative to the baseline"
            )
        qty_ref = alloc.get("hasActualQuantity")
        if not qty_ref:
            draws.append(Draw(_parse(beginning), None, alloc.get("name"), f"input Allocation {alloc.get('name')!r} has no actual quantity"))
            continue
        try:
            grams = _grams(client, food_type_id, client.get_all("Measurement", qty_ref["id"])["result"], "input Allocation quantity")
            draws.append(Draw(_parse(beginning), grams, alloc.get("name")))
        except QuantityError as problem:
            draws.append(Draw(_parse(beginning), None, alloc.get("name"), str(problem)))
    return draws


def _level_at(client, food_type_id, baselines, draws, at: datetime) -> tuple[float, dict] | None:
    """(grams on hand at `at`, the baseline Measurement used), or None if no
    Measurement had been made by then. Sec 4.1.1, literally: the latest
    baseline at or before `at`, minus every input draw from that baseline's
    instant up to and including `at`.

    The lower bound is inclusive, on purpose: a Process at the EXACT instant
    of the baseline counts as consumption. Nothing recorded says which came
    first, so this is a stated convention, not an accident: a weighing at the
    same instant as a use is read as taken BEFORE it. Overstating stock
    (planning a meal around food already used) is the costlier error, while
    the opposite reading costs a slightly conservative count. Data-model.md
    Sec 4.1.1 says "after", so this deviates from it on purpose (Sec 18 J8).
    A strict reading would need the model to carry the order, which it does
    not."""
    known = [(t, m) for t, m in baselines if t <= at]
    if not known:
        return None
    baseline_time, baseline = known[-1]
    level = _grams(client, food_type_id, baseline, "baseline mass Measurement")
    for draw in draws:
        if draw.began < baseline_time or draw.began > at:
            continue
        if draw.problem:
            raise QuantityError(draw.problem)
        level -= draw.grams
    return level, baseline


def _portion_context(client, quality: dict) -> tuple[dict, str | None]:
    bearer = quality.get("inheresIn")
    bearer_full = client.get_all(bearer["type"], bearer["id"])["result"] if bearer else {}
    return bearer_full, (bearer_full.get("instanceOf") or {}).get("id")


def current_magnitude(client, quality_id: str, now: datetime) -> float | None:
    """Sec 4.1.1, literally, as of `now`, in grams. None if the Quality has
    no observed/imputed Measurement made at or before `now` to start from.

    Everything is bounded by `now`. The baseline is the latest observed-or-
    imputed Measurement at or BEFORE now, and only Processes that began
    between that baseline and now count as consumption. This used to ignore
    `now` in choosing the baseline, so a Measurement dated tomorrow became
    today's stock and a Process that hasn't happened yet already consumed it
    (found by external review). Asking about the past now gives the past.

    Quantities are converted to grams before any arithmetic: a Measurement in
    kg or oz and an Allocation in another unit used to be added and
    subtracted as bare numbers. An unusable quantity (no unit, unrecognised
    unit, an input Allocation with no actual quantity, or a Process with no
    start time) raises QuantityError. Only Mass Qualities are supported; that
    is all physical_on_hand tracks, and converting to grams is meaningless for
    any other kind."""
    return _magnitude(client, client.get_all("Quality", quality_id)["result"], now)


def _magnitude(client, quality: dict, now: datetime) -> float | None:
    """current_magnitude for a Quality that is already loaded."""
    kind = (quality.get("hasKind") or {}).get("name")
    if kind != "Mass":
        raise QuantityError(f"current_magnitude supports Mass Qualities only; {quality.get('name')!r} is {kind!r}")
    bearer, food_type_id = _portion_context(client, quality)
    level = _level_at(client, food_type_id, _baselines(client, quality), _draws(client, bearer, food_type_id), now)
    return None if level is None else level[0]


@dataclass
class Overdraw:
    """More was used than there was, at the time of one Process (invariant 15)."""

    portion: str
    at: datetime
    shortfall_grams: float
    baseline_status: str            # "observed" is a real violation; "imputed" is informative

    @property
    def fatal(self) -> bool:
        return self.baseline_status == "observed"


def overdraws(client, portion: dict, tolerance_grams: float = 1e-6) -> list[Overdraw]:
    """Invariant 15 for one portion: at the time of each Process that drew on
    it, the summed input quantities so far (since the applicable baseline)
    must not exceed what was on hand. Checked at every draw's own time, not
    only now, so a later weighing that resets the level cannot hide an
    earlier overdraw.

    Data-model.md Sec 11: a violation against an `imputed` baseline is
    informative rather than fatal (the Type default was wrong for this
    instance; the fix is an `observed` Measurement), hence Overdraw.fatal.
    Draws before the first Measurement can't be judged (nothing to compare
    with) and aren't reported. Raises QuantityError on an unusable quantity,
    as current_magnitude does.

    This is an audit, not a write-time check: a validator would have to
    compute on-hand inside StructrScript, which cannot (see this module's
    docstring). Recording an oversized Allocation is therefore still accepted;
    this is how it gets found."""
    quality = mass_quality(client, portion)
    if quality is None:
        return []
    bearer, food_type_id = _portion_context(client, quality)
    baselines = _baselines(client, quality)
    draws = _draws(client, bearer, food_type_id)
    found = []
    for at in sorted({d.began for d in draws}):
        level = _level_at(client, food_type_id, baselines, draws, at)
        if level is not None and level[0] < -tolerance_grams:
            found.append(Overdraw(portion.get("name") or portion["id"], at, -level[0], level[1].get("status")))
    return found


def find_overdraws(client) -> list[Overdraw]:
    """overdraws() over every portion in the graph."""
    client = ReadCache(client)
    found = []
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for portion in client.get_all(type_name)["result"]:
            found.extend(overdraws(client, portion))
    return found


def shelf_life_days(
    client, perishability_type_id: str, opened_status_name: str = "Sealed", storage_condition_name: str = "Fridge",
) -> float | None:
    """The ShelfLife default for a Perishability type in a given storage
    condition and opened status, in days, or None if none resolves.

    Resolved by (kind, keyedBy) through mealplanner/defaults.py (data-model.md
    Sec 8's compound key, e.g. keyedBy [Fridge, Sealed] vs [Fridge, Opened]):
    an exact key match beats a partial one, and the walk goes up the type
    hierarchy. It used to look only at the type itself and demand an exact
    key set, after the StructrScript resolveDefault turned out to ignore
    keyedBy altogether.

    Both dimensions default to the more conservative/common case when
    unknown -- but note the caller decides that (instance_expiration), and
    that choice is an open question (REVIEW.md #9), not a settled rule."""
    keys = {dt(client, storage_condition_name), dt(client, opened_status_name)}
    resolved = resolve_default(client, perishability_type_id, dt(client, "ShelfLife"), keys)
    if resolved is None:
        return None
    if resolved.quantity.get("unit") != "days" or resolved.quantity.get("value") is None:
        raise ValueError(
            f"ShelfLife default {resolved.default_name!r} must be a number of days; "
            f"got {resolved.quantity.get('value')!r} {resolved.quantity.get('unit')!r}"
        )
    return resolved.quantity["value"]


def container_opened_status(client, portion: dict) -> str | None:
    """The name of the portion's container's opened-status DomainType
    (e.g. "Opened"/"Sealed"), or None if the portion isn't located_in
    any container -- per data-model.md Sec 9: "food in no container is
    outside any opened-status filter rather than undefined." Callers
    decide what None means for their purpose (shelf_life_days treats it
    as "assume Sealed"; an eligibility filter should instead treat it
    as "this filter doesn't apply, don't exclude")."""
    container_ref = portion.get("locatedIn")
    if not container_ref:
        return None
    container = client.get_all("ContainerObject", container_ref["id"])["result"]
    status = container.get("hasOpenedStatus")
    return status["name"] if status else None


def container_storage_condition(client, portion: dict) -> str | None:
    """The name of the portion's container's storage-condition
    DomainType (e.g. "Fridge"/"Freezer"), or None if the portion isn't
    located_in any container -- same "food in no container is outside
    any filter" reasoning as container_opened_status. Callers decide
    what None means (shelf_life_days treats it as "assume Fridge"; an
    eligibility filter should treat it as "this filter doesn't apply")."""
    container_ref = portion.get("locatedIn")
    if not container_ref:
        return None
    container = client.get_all("ContainerObject", container_ref["id"])["result"]
    condition = container.get("hasStorageCondition")
    return condition["name"] if condition else None


def origin_time(client, portion: dict) -> datetime | None:
    """When the portion began to exist: the start of the Process it
    `beginsToExistDuring` (data-model.md Sec 5.5, "purchase date is the
    Process's temporal region"), or None if no such Process is recorded.

    A Process that is recorded but has no start time raises QuantityError
    rather than being ignored, like an input Allocation's Process in
    current_magnitude: a stated origin with no date is malformed, and falling
    back to a weighing would quietly hide it.

    Known limit: a portion divided off a larger one (a Portioning Process)
    begins to exist at the division, so if that is recorded as its origin the
    shelf-life clock restarts there. The model has no parent link to trace it
    back to the purchase."""
    process_ref = portion.get("beginsToExistDuring")
    if not process_ref:
        return None
    process = client.get_all("Process", process_ref["id"])["result"]
    region_ref = process.get("occupiesTemporalRegion")
    beginning = client.get_all("TemporalRegion", region_ref["id"])["result"].get("hasBeginning") if region_ref else None
    if not beginning:
        raise QuantityError(
            f"{portion.get('name')!r} begins to exist during Process {process.get('name')!r}, "
            f"which has no start time, so its expiry cannot be dated"
        )
    return _parse(beginning)


def instance_expiration(client, portion: dict, now: datetime) -> tuple[bool, float | None]:
    """(is_expired, days_until_expiry) for one PortionOfSubstance/
    DiscreteWholeItem. days_until_expiry is negative if already expired.
    (False, None) if there isn't enough data to compute (no mass
    Measurement made by `now`, or no ShelfLife default resolves for its
    Perishability type).

    The clock starts at origin_time() (purchase or the cook that made it), else
    at the earliest observed/imputed mass Measurement made by `now`. A
    Measurement counts only if it is made by `now`, like current_magnitude, and
    at least one is needed: expiry is only reported for food we know exists."""
    perishability = portion.get("hasPerishabilityType")
    quality_full = mass_quality(client, portion) if perishability else None
    if quality_full is None:
        return False, None

    weighed = [t for t, _ in _baselines(client, quality_full) if t <= now]
    if not weighed:
        return False, None
    started = origin_time(client, portion) or weighed[0]
    opened_status = container_opened_status(client, portion) or "Sealed"
    storage_condition = container_storage_condition(client, portion) or "Fridge"
    days = shelf_life_days(client, perishability["id"], opened_status, storage_condition)
    if days is None:
        return False, None
    expiry = started.timestamp() + days * 86400.0
    days_until = (expiry - now.timestamp()) / 86400.0
    return days_until < 0, days_until


def physical_on_hand(client, domain_type_id: str, now: datetime) -> float:
    """Sum of currentMagnitude() across every FoodObject instance whose
    instanceOf is domain_type_id or a descendant of it."""
    types = subtypes_of(client, domain_type_id)
    total = 0.0
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for instance in client.get_all(type_name)["result"]:
            instance_of = instance.get("instanceOf")
            if not instance_of or instance_of["id"] not in types:
                continue
            quality = mass_quality(client, instance)
            if quality is None:
                continue
            magnitude = _magnitude(client, quality, now)
            if magnitude is not None:
                total += magnitude
    return total


def eligible_on_hand_with_urgency(
    client, domain_type_id: str, now: datetime,
    eligible_when_opened: bool | None = None, eligible_when_sealed: bool | None = None,
    eligible_storage_condition_names: set[str] | None = None,
    include_subtypes: bool = True,
    exclude_types: set[str] | None = None,
) -> tuple[float, float | None]:
    """(eligible on-hand quantity [not expired, and passing the opened-
    status/storage-condition filters if given], days-until-expiry of
    the SOONEST-expiring eligible instance, or None).

    eligible_when_opened/eligible_when_sealed: pass a StockPolicy's own
    flags (mealplanner/meal_planning_schema.py) to apply its opened-
    status filter; leave both None for no filtering on that dimension.

    eligible_storage_condition_names: pass a StockPolicy's
    eligibleStorageConditions (as a set of DomainType names, e.g.
    {"Fridge"}) to only count on-hand stock kept in one of those
    conditions -- e.g. a policy checking "what's ready to cook this
    week" reasonably wants Fridge stock only, not Freezer stock that
    still needs thawing. Leave None for no filtering on this dimension.

    include_subtypes: count stock of every descendant type as well
    (default), or only stock whose type is exactly domain_type_id. A
    StockPolicy's includesSubtypes flag feeds this; it was never read
    before, so a policy that said "this exact type only" was counted as
    if it said "and everything below it".

    exclude_types: type ids whose stock is left out of the count, each with
    everything below it. Used so a nested StockPolicy carves its own stock out
    of an ancestor policy's pool instead of the same physical stock counting
    towards both (nearest policy owns the stock).

    An EMPTY eligible_storage_condition_names set means no condition
    qualifies (only stock in no container passes, per Sec 9), not "no
    filter" -- pass None for no filtering. Restrictive policy
    combination (reservation.py) can legitimately produce an empty set.

    Both filters follow data-model.md Sec 9: "food in no container is
    outside any [...] filter rather than undefined" -- an instance with
    no container is never excluded by either filter, regardless of what
    the filter says, since there's nothing to check it against."""
    types = subtypes_of(client, domain_type_id) if include_subtypes else {domain_type_id}
    for excluded_root in exclude_types or ():
        types -= subtypes_of(client, excluded_root)
    total = 0.0
    soonest: float | None = None
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for instance in client.get_all(type_name)["result"]:
            instance_of = instance.get("instanceOf")
            if not instance_of or instance_of["id"] not in types:
                continue
            quality = mass_quality(client, instance)
            if quality is None:
                continue
            magnitude = _magnitude(client, quality, now)
            if not magnitude or magnitude <= 0:
                continue
            is_expired, days_until = instance_expiration(client, instance, now)
            if is_expired:
                continue
            if eligible_when_opened is not None or eligible_when_sealed is not None:
                status = container_opened_status(client, instance)
                if status == "Opened" and eligible_when_opened is False:
                    continue
                if status == "Sealed" and eligible_when_sealed is False:
                    continue
                # status is None (no container) -> filter doesn't apply, per Sec 9
            if eligible_storage_condition_names is not None:
                condition = container_storage_condition(client, instance)
                if condition is not None and condition not in eligible_storage_condition_names:
                    continue
                # condition is None (no container) -> filter doesn't apply, per Sec 9
            total += magnitude
            if days_until is not None and (soonest is None or days_until < soonest):
                soonest = days_until
    return total, soonest
