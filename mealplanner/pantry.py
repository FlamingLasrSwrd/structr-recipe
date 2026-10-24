"""Pantry bookings, after Grocy's stock actions (docs/pantry.md): buy, use, stock take, open, move
(freeze), discard, and cook a planned meal.

Each is written the way the model already records what happens to food (data-model.md Sec 4.1.1,
Sec 5, Sec 5.5), so the inventory engine (inventory.py) needs nothing new to count it:

  buy        a Purchase Process at a TemporalRegion; a PortionOfSubstance that begins to exist during
             it, in a ContainerObject that says where it is kept (sealed); its Mass Quality, with an
             `observed` Measurement of the amount bought. Expiry runs from the purchase (Sec 5.5).
  use        a Use Process with an input Allocation about the portion, its amount an `observed`
             Measurement: current magnitude subtracts it from then on.
  discard    the same with a Discarding Process, for everything left: physical stock goes to none,
             and what was thrown away stays on record (Sec 9's waste feedback).
  stock take a new `observed` Measurement of the portion's mass: a recount is not a revision
             (Sec 4.1.1), so the weighing simply becomes the latest baseline.
  open       the portion's container's opened status set to Opened.
  move       the container's storage condition set (Freezer to freeze). Storage condition is a
             static tag (CLAUDE.md, out of scope), so a portion's shelf life is read as if it had
             always been kept there.
  cook       a Process that concretizes the entry's Plan, drawing each ingredient the recipe buys
             (the ones nutrition counts, nutrition_scope.raw_inputs) for the servings planned,
             from eligible stock, soonest to expire first; the entry is then fulfilledBy it.

A booking is named by a token the caller chooses (a page form makes one per form, the tool one per
run), and every node it writes is found by name before it is created, so repeating a booking (a
page reloaded, a command run twice) writes nothing new (CLAUDE.md hard rule 5). Every node states
its visibility (hard rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.inventory import FMT, container_opened_status, eligible_lots, mass_quality, shelf_life_days
from mealplanner.inventory import _magnitude as magnitude_of
from mealplanner.nutrition_scope import raw_inputs
from mealplanner.typetree import dt
from mealplanner.unit_conversion import convert_to_grams
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

OPERATIONS = "Pantry Operation"                   # the TypeHierarchy of the Processes' kinds
PURCHASE, USE, DISCARDING = "Purchase", "Use", "Discarding"
STORAGE = ("Fridge", "Freezer", "Pantry")
SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}


class PantryError(ValueError):
    pass


@dataclass
class Booking:
    """What one booking wrote: the names of the nodes it created (none when it was booked before)."""
    process: str | None = None
    created: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class _Writer:
    """Find by name, else create: each node of a booking is written once."""

    def __init__(self, client, booking: Booking):
        self.client, self.booking = client, booking

    def ensure(self, type_name: str, name: str, fields: dict) -> str:
        if any(c in name for c in UNSAFE_EXACT_MATCH_CHARS):
            raise PantryError(f"{name!r}: a name cannot hold a comma or a semicolon")
        found = [r for r in self.client.get(f"/structr/rest/{type_name}", params={"name": name})["result"]
                 if r.get("type") == type_name]
        if len(found) > 1:
            raise PantryError(f"two {type_name} nodes are named {name!r}")
        if found:
            return found[0]["id"]
        payload = {k: v for k, v in fields.items() if v is not None}
        node_id = self.client.post(f"/structr/rest/{type_name}", {"name": name, **payload, **SEEN})["result"][0]
        self.booking.created.append(name)
        return node_id


def _time(when: datetime) -> str:
    if when.tzinfo is None:
        raise PantryError("a booking's time needs a time zone")
    return when.strftime(FMT)


def _operation(writer: _Writer, kind: str) -> str:
    """The Process kind, made on first use: a DomainType in the Pantry Operation hierarchy."""
    client = writer.client
    hierarchies = client.get("/structr/rest/TypeHierarchy", params={"name": OPERATIONS})["result"]
    hierarchy = hierarchies[0]["id"] if hierarchies else writer.ensure("TypeHierarchy", OPERATIONS, {})
    return writer.ensure("DomainType", kind, {"hierarchy": hierarchy, "isLookupBearing": False})


def _process(writer: _Writer, kind: str | None, name: str, when: datetime, **fields) -> str:
    region = writer.ensure("TemporalRegion", f"{name} time", {"hasBeginning": _time(when)})
    writer.booking.process = name
    return writer.ensure("Process", name, {"hasKind": _operation(writer, kind) if kind else None,
                                           "occupiesTemporalRegion": region, **fields})


def _portion(client, portion_id: str) -> dict:
    portion = client.get_all("PortionOfSubstance", portion_id)["result"]
    if not portion or portion.get("type") != "PortionOfSubstance":
        raise PantryError(f"{portion_id} is not a portion of food")
    return portion


def _grams(client, food_id: str, food: str, amount: float, unit: str) -> float:
    if amount is None or amount <= 0:
        raise PantryError(f"{food}: an amount must be more than 0")
    grams = convert_to_grams(client, food_id, amount, unit)
    if grams is None:
        raise PantryError(f"{food}: {amount:g} {unit} does not convert to grams (no density or weight per item for it)")
    return grams


def on_hand(client, portion: dict, when: datetime) -> float | None:
    """The portion's current magnitude in grams, or None if it was never weighed."""
    quality = mass_quality(client, portion)
    return None if quality is None else magnitude_of(client, quality, when)


def buy(client, food: str, amount: float, unit: str, when: datetime, token: str, *, storage: str = "Fridge",
        keeps: str | None = None) -> Booking:
    """Book a purchase of `amount` `unit` of `food`, kept in `storage`. Its expiry is its food's
    FoodKeeper shelf life (J31); `keeps` names a Perishability Class for a food without one, and
    without it the class of the latest portion of the same food that has one is taken, if any
    (computed, not stored)."""
    if storage not in STORAGE:
        raise PantryError(f"storage must be one of {', '.join(STORAGE)}, not {storage!r}")
    food_id = dt(client, food)
    _grams(client, food_id, food, amount, unit)
    keeps_id = dt(client, keeps) if keeps else last_perishability(client, food_id)
    booking = Booking()
    w = _Writer(client, booking)
    process = _process(w, PURCHASE, f"Purchase {token}", when)
    name = f"Purchase {token} -- {food}"
    box = w.ensure("ContainerObject", f"{name} container", {
        "hasStorageCondition": dt(client, storage), "hasOpenedStatus": dt(client, "Sealed")})
    portion = w.ensure("PortionOfSubstance", name, {
        "instanceOf": food_id, "beginsToExistDuring": process, "locatedIn": box, "hasPerishabilityType": keeps_id})
    quality = w.ensure("Quality", f"{name} mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion})
    w.ensure("Measurement", f"{name} mass bought", {
        "value": amount, "unit": unit, "status": "observed", "hasTime": _time(when), "isAboutQuality": quality})
    if keeps_id is None and shelf_life_days(client, food_id, "Sealed", storage) is None:
        booking.notes.append(f"{food}: no shelf life known for it in the {storage.lower()}, so no expiry "
                             "(name a perishability class with --keeps)")
    return booking


def last_perishability(client, food_id: str) -> str | None:
    """The Perishability Class of the most recently bought or weighed portion of this food that has one."""
    best = None
    for portion in client.get_all("PortionOfSubstance")["result"]:
        if (portion.get("instanceOf") or {}).get("id") != food_id or not portion.get("hasPerishabilityType"):
            continue
        key = portion.get("createdDate") or ""
        if best is None or key > best[0]:
            best = (key, portion["hasPerishabilityType"]["id"])
    return best[1] if best else None


def _draw(w: _Writer, process: str, portion: dict, grams: float, when: datetime, label: str, spec: str | None = None) -> None:
    name = f"{w.booking.process} -- {label}"
    qty = w.ensure("Measurement", f"{name} amount", {"value": round(grams, 6), "unit": "g", "status": "observed",
                                                     "hasTime": _time(when)})
    w.ensure("Allocation", name, {"isAbout": portion["id"], "hasParticipationRole": "input", "hasActualQuantity": qty,
                                  "process": process, "fulfills": spec})


def use(client, portion_id: str, amount: float, unit: str, when: datetime, token: str) -> Booking:
    """Book `amount` `unit` taken from a portion. More than it holds is refused (invariant 15)."""
    portion = _portion(client, portion_id)
    food = portion.get("instanceOf") or {}
    grams = _grams(client, food.get("id"), food.get("name", portion["name"]), amount, unit)
    have = on_hand(client, portion, when)
    if have is None:
        raise PantryError(f"{portion['name']}: never weighed, so there is nothing to take from it (take stock first)")
    if grams > have + 1e-6:
        raise PantryError(f"{portion['name']}: {grams:.0f} g is more than the {have:.0f} g on hand")
    booking = Booking()
    w = _Writer(client, booking)
    _draw(w, _process(w, USE, f"Use {token}", when), portion, grams, when, portion["name"])
    return booking


def discard(client, portion_id: str, when: datetime, token: str) -> Booking:
    """Book everything left in a portion as thrown away."""
    portion = _portion(client, portion_id)
    have = on_hand(client, portion, when)
    if not have or have <= 0:
        raise PantryError(f"{portion['name']}: nothing on hand to discard")
    booking = Booking()
    w = _Writer(client, booking)
    _draw(w, _process(w, DISCARDING, f"Discard {token}", when), portion, have, when, portion["name"])
    return booking


def stock_take(client, portion_id: str, amount: float, unit: str, when: datetime, token: str) -> Booking:
    """Book a recount: what the portion holds now, weighed or counted. 0 is allowed: it is used up."""
    portion = _portion(client, portion_id)
    food = portion.get("instanceOf") or {}
    if amount is None or amount < 0:
        raise PantryError("a stock take is 0 or more")
    if amount > 0:
        _grams(client, food.get("id"), food.get("name", portion["name"]), amount, unit)
    booking = Booking()
    w = _Writer(client, booking)
    quality = mass_quality(client, portion)
    quality_id = quality["id"] if quality else w.ensure("Quality", f"{portion['name']} mass Quality", {
        "hasKind": dt(client, "Mass"), "inheresIn": portion["id"]})
    w.ensure("Measurement", f"{portion['name']} stock take {token}", {
        "value": amount, "unit": unit, "status": "observed", "hasTime": _time(when), "isAboutQuality": quality_id})
    booking.process = f"{portion['name']} counted"
    return booking


def _container(client, w: _Writer, portion: dict) -> str:
    """The portion's container, or a new one for it: kept in the fridge and sealed, which is what a
    portion in none is taken to be (inventory.instance_expiration)."""
    if portion.get("locatedIn"):
        return portion["locatedIn"]["id"]
    box = w.ensure("ContainerObject", f"{portion['name']} container", {
        "hasStorageCondition": dt(client, "Fridge"), "hasOpenedStatus": dt(client, "Sealed")})
    client.patch(f"/structr/rest/PortionOfSubstance/{portion['id']}", {"locatedIn": box})
    return box


def open_portion(client, portion_id: str) -> Booking:
    """Mark the portion's container opened: its Opened shelf life applies from then on (from purchase,
    as storage does: docs/pantry.md)."""
    portion = _portion(client, portion_id)
    booking = Booking()
    w = _Writer(client, booking)
    box = _container(client, w, portion)
    if container_opened_status(client, {**portion, "locatedIn": {"id": box}}) != "Opened":
        client.patch(f"/structr/rest/ContainerObject/{box}", {"hasOpenedStatus": dt(client, "Opened")})
        booking.notes.append(f"{portion['name']}: opened")
    return booking


def move(client, portion_id: str, storage: str) -> Booking:
    """Keep the portion in `storage` (Freezer to freeze it)."""
    if storage not in STORAGE:
        raise PantryError(f"storage must be one of {', '.join(STORAGE)}, not {storage!r}")
    portion = _portion(client, portion_id)
    booking = Booking()
    w = _Writer(client, booking)
    box = _container(client, w, portion)
    client.patch(f"/structr/rest/ContainerObject/{box}", {"hasStorageCondition": dt(client, storage)})
    booking.notes.append(f"{portion['name']}: kept in the {storage.lower()}")
    return booking


@dataclass
class Shortfall:
    food: str
    needed: float          # grams the servings planned call for
    drawn: float           # grams taken from stock


def cook(client, entry_id: str, when: datetime, token: str) -> tuple[Booking, list[Shortfall]]:
    """Book a planned meal as cooked: each ingredient the recipe buys, scaled from its yield to the
    servings planned, drawn from eligible stock of the food or a food below it, soonest to expire
    first. What stock cannot cover is listed, not drawn (no portion goes below none). The entry is
    then fulfilledBy the cook, so the shopping list and reservations stop counting it."""
    entry = client.get_all("MealPlanEntry", entry_id)["result"]
    if entry.get("fulfilledBy"):
        raise PantryError(f"{entry.get('name')}: already cooked")
    plan_ref = entry.get("references")
    if not plan_ref or entry.get("hasPlannedServings") is None:
        raise PantryError(f"{entry.get('name')}: not a cook (leftovers need nothing from the pantry)")
    plan = client.get_all("Plan", plan_ref["id"])["result"]
    yield_ = plan.get("hasRecipeYield") or {}
    if isinstance(yield_, dict) and "id" in yield_ and "value" not in yield_:
        yield_ = client.get_all("QuantitySpecification", yield_["id"])["result"]
    if yield_.get("unit") != "servings" or not yield_.get("value"):
        raise PantryError(f"{plan.get('name')}: no yield in servings, so its amounts cannot be scaled")
    scale = entry["hasPlannedServings"] / yield_["value"]
    booking = Booking()
    w = _Writer(client, booking)
    process = _process(w, None, f"Cook {token} -- {plan.get('name')}", when, concretizes=plan["id"])
    short: list[Shortfall] = []
    for step, spec in raw_inputs(client, plan):
        food = spec["specifies"]
        qty_ref = spec.get("hasSpecifiedQuantity")
        qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"] if qty_ref else {}
        grams = convert_to_grams(client, food["id"], qty.get("value"), qty.get("unit")) if qty.get("value") else None
        if not grams:
            booking.notes.append(f"{food.get('name')}: no amount in the recipe, so none is drawn")
            continue
        need, left = grams * scale, grams * scale
        for lot in eligible_lots(client, food["id"], when):
            if left <= 1e-9:
                break
            take = min(left, lot.grams)
            portion = client.get_all("PortionOfSubstance", lot.portion_id)["result"]
            _draw(w, process, portion, take, when, f"{food.get('name')} from {lot.name}", spec["id"])
            left -= take
        if left > 1e-6:
            short.append(Shortfall(food.get("name"), need, need - left))
    client.patch(f"/structr/rest/MealPlanEntry/{entry_id}", {"fulfilledBy": process})
    return booking, short
