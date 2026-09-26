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

Sec 9's eligibility filter is SIMPLIFIED here to "not expired" only --
storage-condition and opened-status filtering (the full
StockPolicy.eligibleStorageConditions/eligibleWhenOpened/eligibleWhenSealed
match) is NOT implemented. That's a real, deliberate scope cut: this
project's test inventory doesn't yet track which container/storage
condition a given portion actually sits in, and building that out is
a separate piece of curation work. Flagged, not silently assumed.

Expiration is computed as (the bearer's latest observed/imputed mass
Measurement's hasTime) + (resolveDefault(ShelfLife) on the bearer's
Perishability type, in days) -- Sec 5.5's "original expiration is
purchase time + shelf-life default" is approximated using the mass
Measurement's own timestamp rather than a real Purchase Process's
temporal region, since Purchase Process modeling itself isn't built.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mealplanner.defaults import resolve_default
from mealplanner.typetree import ancestors_or_self, subtypes_of  # noqa: F401 (re-exported)
from mealplanner.unit_conversion import QuantityError, convert_to_grams

FMT = "%Y-%m-%dT%H:%M:%S%z"


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, FMT)


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


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
    quality = client.get_all("Quality", quality_id)["result"]
    kind = (quality.get("hasKind") or {}).get("name")
    if kind != "Mass":
        raise QuantityError(f"current_magnitude supports Mass Qualities only; {quality.get('name')!r} is {kind!r}")
    bearer = quality.get("inheresIn")
    bearer_full = client.get_all(bearer["type"], bearer["id"])["result"] if bearer else {}
    food_type_id = (bearer_full.get("instanceOf") or {}).get("id")

    measurements = [
        client.get_all("Measurement", m["id"])["result"]
        for m in quality.get("measurements", [])
    ]
    baseline = [
        m for m in measurements
        if m.get("status") in ("observed", "imputed") and m.get("hasTime") and _parse(m["hasTime"]) <= now
    ]
    if not baseline:
        return None
    latest = max(baseline, key=lambda m: _parse(m["hasTime"]))
    latest_time = _parse(latest["hasTime"])
    on_hand = _grams(client, food_type_id, latest, "baseline mass Measurement")

    consumed = 0.0
    for alloc_ref in bearer_full.get("allocationsAbout", []):
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
        began = _parse(beginning)
        # ">=" on the lower bound, not ">": a Process at the EXACT instant of
        # the baseline Measurement still counts as consumption. Test data
        # built from one `NOW` ties exactly, and a strict comparison read a
        # portion whose whole 454 g was used by a same-instant Process as
        # still holding all of it. That leaves "measurement before or after
        # consumption at the same instant" undecidable; it is a known open
        # question (REVIEW.md #18), not a settled rule.
        if began < latest_time or began > now:
            continue
        qty_ref = alloc.get("hasActualQuantity")
        if not qty_ref:
            raise QuantityError(f"input Allocation {alloc.get('name')!r} has no actual quantity")
        consumed += _grams(client, food_type_id, client.get_all("Measurement", qty_ref["id"])["result"], "input Allocation quantity")

    return on_hand - consumed


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


def instance_expiration(client, portion: dict, now: datetime) -> tuple[bool, float | None]:
    """(is_expired, days_until_expiry) for one PortionOfSubstance/
    DiscreteWholeItem. days_until_expiry is negative if already expired.
    (None, None) if there isn't enough data to compute (no mass
    Measurement, or no ShelfLife default resolves for its Perishability
    type)."""
    mass_quality = next(
        (q for q in portion.get("bearerOf", []) if q["type"] == "Quality"), None
    )
    perishability = portion.get("hasPerishabilityType")
    if not mass_quality or not perishability:
        return False, None
    quality_full = client.get_all("Quality", mass_quality["id"])["result"]
    if (quality_full.get("hasKind") or {}).get("name") != "Mass":
        # bearerOf may hold several Qualities -- find the mass one specifically
        mass_quality = next(
            (
                q for q in portion.get("bearerOf", [])
                if q["type"] == "Quality"
                and (client.get_all("Quality", q["id"])["result"].get("hasKind") or {}).get("name") == "Mass"
            ),
            None,
        )
        if not mass_quality:
            return False, None
        quality_full = client.get_all("Quality", mass_quality["id"])["result"]

    baseline = [
        client.get_all("Measurement", m["id"])["result"]
        for m in quality_full.get("measurements", [])
    ]
    # Bounded by `now` like current_magnitude: a Measurement dated in the
    # future must not push an expiry date out.
    baseline = [
        m for m in baseline
        if m.get("status") in ("observed", "imputed") and m.get("hasTime") and _parse(m["hasTime"]) <= now
    ]
    if not baseline:
        return False, None
    latest = max(baseline, key=lambda m: _parse(m["hasTime"]))
    opened_status = container_opened_status(client, portion) or "Sealed"
    storage_condition = container_storage_condition(client, portion) or "Fridge"
    days = shelf_life_days(client, perishability["id"], opened_status, storage_condition)
    if days is None:
        return False, None
    expiry = _parse(latest["hasTime"]).timestamp() + days * 86400.0
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
            mass_quality = next(
                (
                    q for q in instance.get("bearerOf", [])
                    if q["type"] == "Quality"
                    and (client.get_all("Quality", q["id"])["result"].get("hasKind") or {}).get("name") == "Mass"
                ),
                None,
            )
            if not mass_quality:
                continue
            magnitude = current_magnitude(client, mass_quality["id"], now)
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
            mass_quality = next(
                (
                    q for q in instance.get("bearerOf", [])
                    if q["type"] == "Quality"
                    and (client.get_all("Quality", q["id"])["result"].get("hasKind") or {}).get("name") == "Mass"
                ),
                None,
            )
            if not mass_quality:
                continue
            magnitude = current_magnitude(client, mass_quality["id"], now)
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
