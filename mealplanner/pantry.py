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
  stock take a Stock take Process with the portion its participant, and a new `observed` Measurement
             of the portion's mass: a recount is not a revision (Sec 4.1.1), so the weighing simply
             becomes the latest baseline.
  open       an Opening Process, and the portion's container's opened status set to Opened. The first
             use of a sealed portion, or a cook's draw on one, that leaves some of it opens it too.
  move       a Move Process, and the container's storage condition set (Freezer to freeze). Storage condition is a
             static tag (CLAUDE.md, out of scope), so a portion's shelf life is read as if it had
             always been kept there.
  cook       a Process that concretizes the entry's Plan, drawing each ingredient the recipe buys
             (the ones nutrition counts, nutrition_scope.raw_inputs) for the servings planned,
             from eligible stock, soonest to expire first; the entry is then fulfilledBy it.

A booking is named by a token the caller chooses (a page form makes one per form, the tool one per
run), and every node it writes is found by name before it is created, so repeating a booking (a
page reloaded, a command run twice) writes nothing new (CLAUDE.md hard rule 5). Every node states
its visibility (hard rule 4).

Each booking's Process names who made it, `wasAssociatedWith` a Person (PROV; data-model.md K1), when
`by` gives one: the pages give the signed-in Person (`$.me`), the tool the Person it signs in as or
the one `--by` names (`signed_in_person`, `person_named`). A stock take, an opening and a move each
write a Process too (2026-11-23), so every booking names who made it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.defaults import resolve_default
from mealplanner.inventory import (FMT, assumed_storage, container_opened_status, eligible_lots, mass_quality,
                                   shelf_life_days)
from mealplanner.inventory import _magnitude as magnitude_of
from mealplanner.nutrition_scope import raw_inputs
from mealplanner.typetree import ancestors_or_self, dt
from mealplanner.unit_conversion import convert_to_grams
from structr_client import ReadCache
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS, StructrError

OPERATIONS = "Pantry Operation"                   # the TypeHierarchy of the Processes' kinds
PURCHASE, USE, DISCARDING = "Purchase", "Use", "Discarding"
STOCK_TAKE, OPENING, MOVE = "Stock take", "Opening", "Move"
STORAGE = ("Fridge", "Freezer", "Pantry")
# Less than this on hand shows as 0 g, and counts as used up. A Use typed as the rounded amount shown ("996 g",
# of what 32 fl oz converts to, 996.0005 g) leaves a crumb that would otherwise stay in the pantry for good,
# with its expiry. The pages' USED_UP_G (pages/lib/30_stock.js) is the same number. It is also how far a Use
# may miss what the portion holds and count as all of it (`use`): 996.6 g shows as "997 g", and 997 g used is
# all of it, not more than there is.
USED_UP_G = 0.5
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


def _process(writer: _Writer, kind: str | None, name: str, when: datetime, by: str | None = None, **fields) -> str:
    region = writer.ensure("TemporalRegion", f"{name} time", {"hasBeginning": _time(when)})
    writer.booking.process = name
    return writer.ensure("Process", name, {"hasKind": _operation(writer, kind) if kind else None,
                                           "occupiesTemporalRegion": region,
                                           "wasAssociatedWith": [by] if by else None, **fields})


def person_named(client, name: str) -> str:
    """The id of the one Person of this name: who made a booking, given by name (tools/pantry.py --by)."""
    found = [r for r in client.get("/structr/rest/Person", params={"name": name})["result"] if r.get("type") == "Person"]
    if len(found) != 1:
        raise PantryError(f"expected one Person named {name!r}, found {len(found)}")
    return found[0]["id"]


def signed_in_person(client) -> str | None:
    """The Person the client is signed in as, if it is one (a Person is also a Structr account, K1), as the
    pages take `$.me`; None for any other account, such as the tools' (mealplanner-tools)."""
    me = client.get("/structr/rest/me")["result"]
    me = me[0] if isinstance(me, list) and me else me
    return me["id"] if isinstance(me, dict) and me.get("type") == "Person" else None


def _portion(client, portion_id: str) -> dict:
    portion = client.get_all("PortionOfSubstance", portion_id)["result"]
    if not portion or portion.get("type") != "PortionOfSubstance":
        raise PantryError(f"{portion_id} is not a portion of food")
    return portion


def _portion_or_none(client, node_id: str) -> dict | None:
    """The PortionOfSubstance of this id, or None for a lot of another kind (a DiscreteWholeItem)."""
    try:
        node = client.get_all("PortionOfSubstance", node_id)["result"]
    except StructrError as exc:
        if exc.status == 404:
            return None
        raise
    return node if node and node.get("type") == "PortionOfSubstance" else None


def _grams(client, food_id: str, food: str, amount: float, unit: str) -> float:
    if amount is None or not math.isfinite(amount) or amount <= 0:
        raise PantryError(f"{food}: an amount must be a number more than 0")
    grams = convert_to_grams(client, food_id, amount, unit)
    if grams is None:
        raise PantryError(f"{food}: {amount:g} {unit} does not convert to grams (no density or weight per item for it)")
    return grams


def on_hand(client, portion: dict, when: datetime) -> float | None:
    """The portion's current magnitude in grams, or None if it was never weighed."""
    quality = mass_quality(client, portion)
    return None if quality is None else magnitude_of(client, quality, when)


def buy(client, food: str, amount: float, unit: str, when: datetime, token: str, *, storage: str = "Fridge",
        keeps: str | None = None, by: str | None = None) -> Booking:
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
    _purchase(client, _Writer(client, booking), food, food_id, [(amount, unit)], storage, keeps_id, when, token, by)
    if keeps_id is None and shelf_life_days(client, food_id, "Sealed", storage) is None:
        booking.notes.append(f"{food}: no shelf life known for it in the {storage.lower()}, so no expiry "
                             "(name a perishability class with --keeps)")
    return booking


def _purchase(client, w: _Writer, food: str, food_id: str, amounts: list[tuple[float, str]], storage: str,
              keeps_id: str | None, when: datetime, token: str, by: str | None) -> list[str]:
    """A Purchase Process and, for each (amount, unit), a sealed portion of the food in a container of its
    own kept in `storage`, with its mass bought: the first named "Purchase <token> -- <food>", as Buy names
    its one, the rest "... #2", "... #3". The portions' ids."""
    process = _process(w, PURCHASE, f"Purchase {token}", when, by)
    portions = []
    for i, (amount, unit) in enumerate(amounts):
        name = f"Purchase {token} -- {food}" + (f" #{i + 1}" if i else "")
        box = w.ensure("ContainerObject", f"{name} container", {
            "hasStorageCondition": dt(client, storage), "hasOpenedStatus": dt(client, "Sealed")})
        portion = w.ensure("PortionOfSubstance", name, {
            "instanceOf": food_id, "beginsToExistDuring": process, "locatedIn": box, "hasPerishabilityType": keeps_id})
        quality = w.ensure("Quality", f"{name} mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion})
        w.ensure("Measurement", f"{name} mass bought", {
            "value": amount, "unit": unit, "status": "observed", "hasTime": _time(when), "isAboutQuality": quality})
        portions.append(portion)
    return portions


# A food sold frozen, by its name or the name of a food above it ("Frozen green peas"): kept in the freezer
FROZEN = re.compile(r"\bfrozen\b", re.IGNORECASE)
MAX_PIECES = 99                 # more packages than this on one line is a mistake, not a shop


def default_storage(client, food_id: str) -> str:
    """Where a purchase from the shopping list is put away when the line does not say (docs/pantry.md,
    "Ticking the shopping list"): in the freezer for a food sold frozen (its name, or a food's above it,
    says so), else where the pantry takes a portion in no container to be kept (inventory.assumed_storage,
    J31): of the fridge and the pantry, where its food keeps longest unopened, the fridge on a tie or with
    neither. Not FoodKeeper's freezer figure alone, which it gives for milk and fresh tomatoes too, nor
    any pantry figure, which it gives grapes for a day. A product has its food's."""
    for type_id in ancestors_or_self(client, food_id):
        if FROZEN.search(client.get_all("DomainType", type_id)["result"].get("name") or ""):
            return "Freezer"
    return assumed_storage(client, {"instanceOf": {"id": food_id}})


def buy_line(client, food: str, pieces: list[float], when: datetime, token: str, *, storage: str | None = None,
             by: str | None = None) -> Booking:
    """Book what a line of the shopping list bought (pages/shopping.js, "Put ticked items into the pantry"):
    `pieces` the grams of each package, as a recipe weighs them (shopping.Line.pieces), each a portion in a
    container of its own, so that opening one package opens no other; a line bought loose or by count is
    one piece. `food` is the line's food, or a product of it chosen instead. Kept in `storage`, else where
    default_storage says. Its perishability class is the latest portion's of the food, as Buy's is."""
    if storage is not None and storage not in STORAGE:
        raise PantryError(f"storage must be one of {', '.join(STORAGE)}, not {storage!r}")
    if not pieces:
        raise PantryError(f"{food}: nothing to put away")
    if len(pieces) > MAX_PIECES:
        raise PantryError(f"{food}: {len(pieces)} packages on one line is more than {MAX_PIECES}")
    for grams in pieces:
        if grams is None or not isinstance(grams, (int, float)) or not math.isfinite(grams) or grams <= 0:
            raise PantryError(f"{food}: each package must weigh a number of grams more than 0")
    food_id = dt(client, food)
    where = storage or default_storage(client, food_id)
    keeps_id = last_perishability(client, food_id)
    booking = Booking()
    _purchase(client, _Writer(client, booking), food, food_id, [(round(g, 6), "g") for g in pieces], where, keeps_id,
              when, token, by)
    booking.notes.append(f"{food}: " + (f"{len(pieces)} packages, " if len(pieces) > 1 else "")
                         + f"{sum(pieces):,.0f} g, kept in the {where.lower()}")
    if keeps_id is None and shelf_life_days(client, food_id, "Sealed", where) is None:
        booking.notes.append(f"{food}: no shelf life known for it in the {where.lower()}, so no expiry")
    return booking


def line_purchase(client, food: str, *, pieces=None, product: str | None = None, count=None, grams=None,
                  buy=None) -> tuple[str, list[float]]:
    """What a shopping line's form asks to book (pages/lib/50_pantry.js linePurchase): (the food or product, the
    grams of each piece). The line's own packages (`pieces`), or `grams` bought instead, as one piece; or a
    product of the line's food chosen instead, so many packages (`count`, else enough to cover `buy` grams)
    of what one holds."""
    from mealplanner.products import PACKAGE_SIZE, product_ids     # products reads the vocabulary module; only here
    asked = lambda v: v is not None and str(v).strip() != ""      # noqa: E731
    food_id = dt(client, food)
    if asked(product):
        product_id = dt(client, product)
        if product_id not in product_ids(client) or food_id not in ancestors_or_self(client, product_id):
            raise PantryError(f"{product}: not a product of {food}")
        size = resolve_default(client, product_id, dt(client, PACKAGE_SIZE))
        each = convert_to_grams(client, product_id, size.quantity.get("value"), size.quantity.get("unit")) if size else None
        if not each or each <= 0:
            raise PantryError(f"{product}: no package size is known for it, so give the grams bought instead")
        if asked(count):
            n = _number(count)
            if not math.isfinite(n) or n < 1 or n != int(n):
                raise PantryError(f"{product}: the number of packages is a whole number, 1 or more")
            n = int(n)
        else:
            need = _number(buy) if asked(buy) else 0.0
            n = max(1, math.ceil((need if math.isfinite(need) else 0.0) / each - 1e-9))
        if n > MAX_PIECES:
            raise PantryError(f"{product}: {n} packages on one line is more than {MAX_PIECES}")
        return product, [each] * n
    if asked(grams):
        return food, [_number(grams)]
    if isinstance(pieces, str):
        pieces = [_number(p) for p in pieces.split(",") if p.strip()]
    return food, list(pieces or [])


def _number(value) -> float:
    """A form's number, as JavaScript's Number() reads it: NaN where it is none, which buy_line then refuses."""
    try:
        return float(str(value).strip())
    except ValueError:
        return math.nan


# What an undone purchase's record keeps of each node (unbuy): what _purchase wrote, so that it can be made again
RECORD_KEYS = {
    "TemporalRegion": ("hasBeginning",),
    "Process": ("hasKind", "occupiesTemporalRegion", "wasAssociatedWith"),
    "ContainerObject": ("hasStorageCondition", "hasOpenedStatus"),
    "PortionOfSubstance": ("instanceOf", "beginsToExistDuring", "locatedIn", "hasPerishabilityType"),
    "Quality": ("hasKind", "inheresIn"),
    "Measurement": ("value", "unit", "status", "hasTime", "isAboutQuality"),
}


def _recorded(node: dict) -> dict:
    """A node as an undo's record keeps it: its type, id, name and RECORD_KEYS, a reference as {id, name}."""
    def ref(value):
        if isinstance(value, list):
            return [ref(v) for v in value]
        if isinstance(value, dict):
            return {"id": value.get("id"), "name": value.get("name")}
        return value
    out = {"type": node["type"], "id": node["id"], "name": node["name"]}
    for key in RECORD_KEYS[node["type"]]:
        value = node.get(key)
        out[key] = ref(value) if value not in (None, []) else None
    return out


def purchase_nodes(client, token: str) -> list[dict]:
    """What the purchase of this token wrote, in the order unbuy deletes it (each portion's Measurements,
    its Quality, the portion, its container; then the Process and its time), or a PantryError saying why
    it cannot be taken back: no such purchase, or something since rests on one of its portions (a use, a
    discard, a cook or a reservation draws on it; a stock take weighed it; it was opened or moved). After
    that the purchase stands, and Use, Count or Discard corrects it."""
    found = [r for r in client.get("/structr/rest/Process", params={"name": f"Purchase {token}"})["result"]
             if r.get("type") == "Process"]
    if len(found) != 1:
        raise PantryError(f"no purchase Purchase {token}" if not found else f"two purchases named Purchase {token}")
    process = client.get_all("Process", found[0]["id"])["result"]
    if (process.get("hasKind") or {}).get("name") != PURCHASE:
        raise PantryError(f"Purchase {token} is not a purchase")
    nodes = []
    for ref in sorted(process.get("thingsBegunDuring") or [], key=lambda r: r.get("name") or ""):
        if ref.get("type") != "PortionOfSubstance":
            raise PantryError(f"Purchase {token}: {ref.get('name')} is no portion of food, so it is not undone here")
        portion = client.get_all("PortionOfSubstance", ref["id"])["result"]
        if portion.get("allocationsAbout"):
            raise PantryError(f"{portion['name']}: some of it has been used, so it stays (use Count or Discard instead)")
        if portion.get("processesWithParticipant"):
            raise PantryError(f"{portion['name']}: weighed, opened or moved since, so it stays (use Count or Discard instead)")
        quality = mass_quality(client, portion)
        measurements = [client.get_all("Measurement", m["id"])["result"] for m in (quality or {}).get("measurements", [])]
        if any(m["name"] != f"{portion['name']} mass bought" for m in measurements):
            raise PantryError(f"{portion['name']}: weighed since, so it stays (use Count or Discard instead)")
        nodes += measurements
        if quality:
            nodes.append(quality)
        nodes.append(portion)
        if portion.get("locatedIn"):
            box = client.get_all("ContainerObject", portion["locatedIn"]["id"])["result"]
            if box["name"] == f"{portion['name']} container":
                nodes.append(box)               # its own; one shared with other portions stays
    nodes.append(process)
    region = process.get("occupiesTemporalRegion")
    if region and region.get("name") == f"Purchase {token} time":
        nodes.append(client.get_all("TemporalRegion", region["id"])["result"])
    return nodes


def undo_record(token: str, nodes: list[dict], when: datetime, by: str | None) -> dict:
    """The record an undone purchase leaves (the owner's decision, 2026-11-23, docs/todo.md "Undo a booking"):
    every node it deleted, as text, so that it can be made again."""
    return {"undone": f"Purchase {token}", "at": _time(when), "by": by, "nodes": [_recorded(n) for n in nodes]}


def record_name(token: str, when: datetime) -> str:
    return f"undone Purchase {token} {when.strftime('%Y%m%dT%H%M%S')}.json"


def unbuy(client, token: str, when: datetime, *, by: str | None = None, keep=None) -> Booking:
    """Take back the purchase of this token while nothing rests on it (purchase_nodes): a record of what it
    wrote is kept first, by `keep(name, text)` (tools/pantry.py stores it as a file on the instance), then
    every node it wrote is deleted. The Booking lists what was deleted, as `created` lists what a booking
    wrote."""
    nodes = purchase_nodes(client, token)
    record = undo_record(token, nodes, when, by)
    if keep is not None:
        keep(record_name(token, when), json.dumps(record, indent=1, sort_keys=True))
    booking = Booking(process=f"Purchase {token}")
    for node in nodes:
        client.delete(f"/structr/rest/{node['type']}/{node['id']}")
        booking.created.append(node["name"])
    booking.notes.append(f"Purchase {token}: taken back")
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


def use(client, portion_id: str, amount: float, unit: str, when: datetime, token: str, *, by: str | None = None) -> Booking:
    """Book `amount` `unit` taken from a portion. More than it holds is refused (invariant 15), but an amount
    within USED_UP_G of what it holds, either way, is all of it: what the pages and the tool show is rounded to
    the gram, so the amount shown, used, may be up to half a gram more than there is."""
    portion = _portion(client, portion_id)
    food = portion.get("instanceOf") or {}
    grams = _grams(client, food.get("id"), food.get("name", portion["name"]), amount, unit)
    have = on_hand(client, portion, when)
    if have is None:
        raise PantryError(f"{portion['name']}: never weighed, so there is nothing to take from it (take stock first)")
    if have <= 0:
        raise PantryError(f"{portion['name']}: nothing on hand to take from it")
    if -USED_UP_G <= have - grams < USED_UP_G:
        grams = have                    # the amount shown, or one that would leave a crumb: all of it
    elif grams > have:
        raise PantryError(f"{portion['name']}: {grams:.0f} g is more than the {have:.0f} g on hand")
    booking = Booking()
    w = _Writer(client, booking)
    _draw(w, _process(w, USE, f"Use {token}", when, by), portion, grams, when, portion["name"])
    if grams < have:
        _opened_by_use(client, w, portion)
    return booking


def discard(client, portion_id: str, when: datetime, token: str, *, by: str | None = None) -> Booking:
    """Book everything left in a portion as thrown away."""
    portion = _portion(client, portion_id)
    have = on_hand(client, portion, when)
    if not have or have <= 0:
        raise PantryError(f"{portion['name']}: nothing on hand to discard")
    booking = Booking()
    w = _Writer(client, booking)
    _draw(w, _process(w, DISCARDING, f"Discard {token}", when, by), portion, have, when, portion["name"])
    return booking


def stock_take(client, portion_id: str, amount: float, unit: str, when: datetime, token: str, *,
               by: str | None = None) -> Booking:
    """Book a recount: what the portion holds now, weighed or counted. 0 is allowed: it is used up."""
    portion = _portion(client, portion_id)
    food = portion.get("instanceOf") or {}
    if amount is None or not math.isfinite(amount) or amount < 0:
        raise PantryError("a stock take is 0 or more")
    if amount > 0:
        _grams(client, food.get("id"), food.get("name", portion["name"]), amount, unit)
    booking = Booking()
    w = _Writer(client, booking)
    quality = mass_quality(client, portion)
    quality_id = quality["id"] if quality else w.ensure("Quality", f"{portion['name']} mass Quality", {
        "hasKind": dt(client, "Mass"), "inheresIn": portion["id"]})
    _process(w, STOCK_TAKE, f"Stock take {token}", when, by, hasParticipant=[portion["id"]])
    w.ensure("Measurement", f"{portion['name']} stock take {token}", {
        "value": amount, "unit": unit, "status": "observed", "hasTime": _time(when), "isAboutQuality": quality_id})
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


def _opened_by_use(client, w: _Writer, portion: dict) -> None:
    """The first use of a sealed portion opens it (the owner's rule, 2026-11-23): its Opened shelf life
    applies from then on. A use that leaves none needs no opening, so callers do not call this then."""
    box = _container(client, w, portion)
    if container_opened_status(client, {**portion, "locatedIn": {"id": box}}) != "Opened":
        client.patch(f"/structr/rest/ContainerObject/{box}", {"hasOpenedStatus": dt(client, "Opened")})
        w.booking.notes.append(f"{portion['name']}: opened by this use")


def open_portion(client, portion_id: str, when: datetime, token: str, *, by: str | None = None) -> Booking:
    """Mark the portion's container opened: its Opened shelf life applies from then on (from purchase,
    as storage does: docs/pantry.md)."""
    portion = _portion(client, portion_id)
    booking = Booking()
    w = _Writer(client, booking)
    box = _container(client, w, portion)
    _process(w, OPENING, f"Open {token}", when, by, hasParticipant=[portion["id"]])
    if container_opened_status(client, {**portion, "locatedIn": {"id": box}}) != "Opened":
        client.patch(f"/structr/rest/ContainerObject/{box}", {"hasOpenedStatus": dt(client, "Opened")})
        booking.notes.append(f"{portion['name']}: opened")
    return booking


def move(client, portion_id: str, storage: str, when: datetime, token: str, *, by: str | None = None) -> Booking:
    """Keep the portion in `storage` (Freezer to freeze it)."""
    if storage not in STORAGE:
        raise PantryError(f"storage must be one of {', '.join(STORAGE)}, not {storage!r}")
    portion = _portion(client, portion_id)
    booking = Booking()
    w = _Writer(client, booking)
    box = _container(client, w, portion)
    _process(w, MOVE, f"Move {token}", when, by, hasParticipant=[portion["id"]])
    client.patch(f"/structr/rest/ContainerObject/{box}", {"hasStorageCondition": dt(client, storage)})
    booking.notes.append(f"{portion['name']}: kept in the {storage.lower()}")
    return booking


@dataclass
class Shortfall:
    food: str
    needed: float          # grams the servings planned call for
    drawn: float           # grams taken from stock


def cook(client, entry_id: str, when: datetime, token: str, *, by: str | None = None) -> tuple[Booking, list[Shortfall]]:
    """Book a planned meal as cooked: each ingredient the recipe buys, scaled from its yield to the
    servings planned, drawn from eligible stock of the food or a food below it, soonest to expire
    first. What stock cannot cover is listed, not drawn (no portion goes below none). The entry is
    then fulfilledBy the cook, so the shopping list and reservations stop counting it."""
    entry = client.get_all("MealPlanEntry", entry_id)["result"]
    if entry.get("fulfilledBy"):
        raise PantryError(f"{entry.get('name')}: already cooked")
    if entry.get("isSkipped"):
        raise PantryError(f"{entry.get('name')}: skipped, so not cooked (undo the skip first)")
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
    process = _process(w, None, f"Cook {token} -- {plan.get('name')}", when, by, concretizes=plan["id"])
    short: list[Shortfall] = []
    inputs = raw_inputs(client, plan)
    # The stock as it was before this cook, and what the cook has taken of each portion so far: two inputs
    # may be one food, or a food and one below it. Each use is an Allocation of its own, so a second draw
    # of a food from one portion is numbered: named alike, it was found by name and never written.
    reads = ReadCache(client)          # read once each, all before the first draw is written
    stock = {f: eligible_lots(reads, f, when) for f in {spec["specifies"]["id"] for _, spec in inputs}}
    taken: dict[str, float] = {}
    drawn: dict[str, int] = {}
    for step, spec in inputs:
        food = spec["specifies"]
        qty_ref = spec.get("hasSpecifiedQuantity")
        qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"] if qty_ref else {}
        grams = convert_to_grams(client, food["id"], qty.get("value"), qty.get("unit")) if qty.get("value") else None
        if not grams:
            booking.notes.append(f"{food.get('name')}: no amount in the recipe, so none is drawn")
            continue
        need, left = grams * scale, grams * scale
        for lot in stock[food["id"]]:
            if left <= 1e-9:
                break
            free = lot.grams - taken.get(lot.portion_id, 0.0)
            if free <= 1e-9:
                continue
            take = min(left, free)
            label = f"{food.get('name')} from {lot.name}"
            drawn[label] = drawn.get(label, 0) + 1
            if drawn[label] > 1:
                label += f" #{drawn[label]}"
            # a lot may be a DiscreteWholeItem, which is no PortionOfSubstance: only its id is needed
            _draw(w, process, {"id": lot.portion_id}, take, when, label, spec["id"])
            taken[lot.portion_id] = taken.get(lot.portion_id, 0.0) + take
            left -= take
        if left > 1e-6:
            short.append(Shortfall(food.get("name"), need, need - left))
    # a draw that leaves some of a sealed portion opens it, as a use does; a whole item (no portion) is left be
    for lots in stock.values():
        for lot in lots:
            if 0 < taken.get(lot.portion_id, 0.0) < lot.grams - 1e-9:
                portion = _portion_or_none(client, lot.portion_id)
                if portion is not None:
                    _opened_by_use(client, w, portion)
                taken.pop(lot.portion_id)           # once, though it is under two foods
    client.patch(f"/structr/rest/MealPlanEntry/{entry_id}", {"fulfilledBy": process})
    return booking, short
