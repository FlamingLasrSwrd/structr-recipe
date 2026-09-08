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

FMT = "%Y-%m-%dT%H:%M:%S%z"


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, FMT)


def current_magnitude(client, quality_id: str, now: datetime) -> float | None:
    """Sec 4.1.1, literally. Returns None if the Quality has no
    observed/imputed Measurement to start from."""
    quality = client.get_all("Quality", quality_id)["result"]
    bearer = quality.get("inheresIn")
    measurements = [
        client.get_all("Measurement", m["id"])["result"]
        for m in quality.get("measurements", [])
    ]
    baseline = [m for m in measurements if m.get("status") in ("observed", "imputed") and m.get("hasTime")]
    if not baseline:
        return None
    latest = max(baseline, key=lambda m: _parse(m["hasTime"]))
    latest_time = _parse(latest["hasTime"])

    consumed = 0.0
    if bearer:
        bearer_full = client.get_all(bearer["type"], bearer["id"])["result"]
        for alloc_ref in bearer_full.get("allocationsAbout", []):
            alloc = client.get_all("Allocation", alloc_ref["id"])["result"]
            if alloc.get("hasParticipationRole") != "input":
                continue
            process_ref = alloc.get("process")
            if not process_ref:
                continue
            process = client.get_all("Process", process_ref["id"])["result"]
            region_ref = process.get("occupiesTemporalRegion")
            if not region_ref:
                continue
            region = client.get_all("TemporalRegion", region_ref["id"])["result"]
            beginning = region.get("hasBeginning")
            if not beginning or _parse(beginning) < latest_time:
                continue
            # Note: ">=" not ">" -- a Process occurring at the EXACT same
            # timestamp as the baseline Measurement still counts as
            # consumption. Found the hard way: test data built from one
            # `NOW` variable naturally produces measurement/process
            # timestamps that tie exactly, and a strict "after" (">")
            # comparison silently under-counted consumption for every
            # such case -- a portion whose entire 454g was used by a
            # same-instant Process read back as still having its full
            # original mass on hand. "Occurred after that Measurement's
            # time" is read here as "at or after" for that reason.
            qty_ref = alloc.get("hasActualQuantity")
            if qty_ref:
                qty = client.get_all("Measurement", qty_ref["id"])["result"]
                consumed += qty.get("value") or 0.0

    return (latest.get("value") or 0.0) - consumed


def _subtypes_of(client, domain_type_id: str) -> set[str]:
    """domain_type_id and every descendant, walking SUBCLASS_OF downward."""
    result = {domain_type_id}
    frontier = [domain_type_id]
    while frontier:
        current = frontier.pop()
        node = client.get_all("DomainType", current)["result"]
        for child in node.get("children", []):
            if child["id"] not in result:
                result.add(child["id"])
                frontier.append(child["id"])
    return result


def shelf_life_days(client, perishability_type_id: str) -> float | None:
    density_kind = client.get("/structr/rest/DomainType", params={"name": "ShelfLife"})["result"][0]["id"]
    result = client.call_method("DomainType", perishability_type_id, "resolveDefault", {"kindId": density_kind})
    if not isinstance(result, dict) or "id" not in result:
        return None
    qty = client.get_all("QuantitySpecification", result["id"])["result"]
    return qty.get("value")


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
    baseline = [m for m in baseline if m.get("status") in ("observed", "imputed") and m.get("hasTime")]
    if not baseline:
        return False, None
    latest = max(baseline, key=lambda m: _parse(m["hasTime"]))
    days = shelf_life_days(client, perishability["id"])
    if days is None:
        return False, None
    expiry = _parse(latest["hasTime"]).timestamp() + days * 86400.0
    days_until = (expiry - now.timestamp()) / 86400.0
    return days_until < 0, days_until


def physical_on_hand(client, domain_type_id: str, now: datetime) -> float:
    """Sum of currentMagnitude() across every FoodObject instance whose
    instanceOf is domain_type_id or a descendant of it."""
    types = _subtypes_of(client, domain_type_id)
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
            if magnitude:
                total += magnitude
    return total


def eligible_on_hand_with_urgency(client, domain_type_id: str, now: datetime) -> tuple[float, float | None]:
    """(eligible on-hand quantity [not expired], days-until-expiry of the
    SOONEST-expiring eligible instance, or None if nothing expiring is
    on hand / no expiration data). Storage-condition/opened-status
    filtering NOT implemented -- see module docstring."""
    types = _subtypes_of(client, domain_type_id)
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
            total += magnitude
            if days_until is not None and (soonest is None or days_until < soonest):
                soonest = days_until
    return total, soonest
