"""Builders for the small physical fixtures the demo scripts share: a
container, and a portion of food with a mass Quality and one observed
Measurement, optionally inside a container. Names follow the pattern the
older scripts already used ("<name> mass Quality", "<name> mass
observation"), so a rebuilt instance matches an existing one.

Created here rather than repeated in each script because the scripts that
need them (17d, 18b) were previously a one-off run of ad-hoc code that was
never committed, which is why a from-scratch build lacked their data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mealplanner.inventory import current_magnitude, instance_expiration

FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def make_container(client, name: str, *, opened: str | None = None, storage: str | None = None,
                   container_type: str = "Tray") -> str:
    fields = {"instanceOf": dt(client, container_type)}
    if opened:
        fields["hasOpenedStatus"] = dt(client, opened)
    if storage:
        fields["hasStorageCondition"] = dt(client, storage)
    return client.upsert("ContainerObject", "name", name, fields)


def make_portion(client, name: str, food_type: str, grams: float, *, age_days: float, now: datetime,
                 perishability: str | None = "Fresh Meat", container_id: str | None = None) -> str:
    """A portion whose only mass observation was taken `age_days` ago."""
    fields = {"instanceOf": dt(client, food_type)}
    if perishability:
        fields["hasPerishabilityType"] = dt(client, perishability)
    if container_id:
        fields["locatedIn"] = container_id
    portion = client.upsert("PortionOfSubstance", "name", name, fields)
    quality = client.upsert("Quality", "name", f"{name} mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion})
    client.upsert("Measurement", "name", f"{name} mass observation", {
        "value": grams, "unit": "g", "status": "observed",
        "hasTime": (now - timedelta(days=age_days)).strftime(FMT), "isAboutQuality": quality,
    })
    return portion


def usable_grams_in_containers(client, food_type_id: str, now: datetime, excluded_by) -> float:
    """Grams of NOT-yet-expired stock of one food type sitting in a container
    for which excluded_by(container_dict) is true.

    An independent way to work out what an eligibility filter should remove:
    it picks portions by their container and skips expired ones itself, rather
    than calling the filter under test. Only the expiry decision and the
    magnitude come from the engine, and those are checked separately.

    Written after a demo hard-coded "the filter removes exactly 400 g" and
    failed on an instance that also held a sealed freezer tray of frozen
    chicken: a check that only holds when no other stock exists is fragile."""
    total = 0.0
    for portion in client.get_all("PortionOfSubstance")["result"]:
        if (portion.get("instanceOf") or {}).get("id") != food_type_id or not portion.get("locatedIn"):
            continue
        container = client.get_all("ContainerObject", portion["locatedIn"]["id"])["result"]
        if not excluded_by(container):
            continue
        expired, _ = instance_expiration(client, portion, now)
        if expired:
            continue
        mass = next(q for q in portion.get("bearerOf", []) if q["type"] == "Quality")
        total += current_magnitude(client, mass["id"], now) or 0.0
    return total
