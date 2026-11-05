"""An export from Grocy (grocy.info), read and mapped onto this model: the first stage of imports
from similar applications (docs/imports.md).

    products                   foods: each matched to a food of data/vocabulary.toml by the owner, in a
                               map file. A match is a judgment (J19), so nothing here makes one: names
                               that look alike are proposed, and only the map confirms.
    quantity units and         grams, millilitres or items: a unit Grocy names as one of ours (Gram,
    their conversions          Liter, Piece) is that unit; a conversion that crosses from a count or a
                               volume to a mass is a weight per item or a density, reported as a fact
                               the vocabulary may want, and used to turn a stock amount into grams.
    locations                  storage conditions: a freezer Grocy flags is the Freezer; a location named
                               Fridge, Freezer or Pantry is that one; any other is named in the map.
    stock entries              Purchase bookings, through mealplanner/pantry.py's buy (and open_portion
                               for an opened one), each named by its Grocy stock id so that importing the
                               same export twice writes nothing new.

Best-before dates, prices, the shopping list and recipes are left for a later stage (docs/imports.md).
Everything but `book` is offline: it reads the export's JSON files and the vocabulary file.
"""

from __future__ import annotations

import difflib
import json
import os
import tomllib
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from mealplanner import pantry
from mealplanner.unit_conversion import UNIT_TABLE

# The REST objects an export holds, each in a file of its own name: GET /api/objects/<name>.
OBJECTS = ("products", "quantity_units", "quantity_unit_conversions", "locations", "stock")
# Grocy's own word for a date that never comes ("never overdue").
NEVER = "2999-12-31"
# A unit name, singular or plural, lowercased -> the unit this project's UNIT_TABLE knows it as.
UNIT_NAMES = {
    "g": "g", "gram": "g", "grams": "g", "gramm": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kilogramm": "kg",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "cup": "cup", "cups": "cup",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "piece": "each", "pieces": "each", "pc": "each", "pcs": "each", "each": "each",
}
# What a stock amount is booked in, by kind, best first: grams need no fact from the vocabulary.
CANONICAL = {"mass": "g", "volume": "ml", "count": "each"}


class GrocyError(ValueError):
    pass


def _num(value) -> float | None:
    """Grocy's API gives numbers as numbers or, in older versions, as strings."""
    if value is None or value == "":
        return None
    return float(value)


def _id(value) -> int | None:
    return None if value is None or value == "" else int(value)


@dataclass(frozen=True)
class Unit:
    id: int
    name: str
    plural: str | None

    @property
    def ours(self) -> str | None:
        """The UNIT_TABLE unit this is, or None (a Pack, a Glass: a count of its own)."""
        for word in (self.name, self.plural):
            if word and word.strip().lower() in UNIT_NAMES:
                return UNIT_NAMES[word.strip().lower()]
        return None

    @property
    def kind(self) -> str | None:
        return UNIT_TABLE[self.ours][0] if self.ours else None


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    stock_unit: int
    purchase_unit: int | None
    location: int | None
    active: bool


@dataclass(frozen=True)
class Location:
    id: int
    name: str
    is_freezer: bool


@dataclass(frozen=True)
class Conversion:
    from_unit: int
    to_unit: int
    factor: float
    product: int | None             # None: the same for every product


@dataclass(frozen=True)
class StockEntry:
    id: int
    product: int
    amount: float
    purchased: date | None
    best_before: date | None
    opened: bool
    location: int | None
    stock_id: str | None
    price: float | None


@dataclass
class Export:
    units: dict[int, Unit]
    products: dict[int, Product]
    locations: dict[int, Location]
    conversions: list[Conversion]
    stock: list[StockEntry]


def _date(value) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def parse_export(objects: dict[str, list[dict]]) -> Export:
    """The five REST objects, as Grocy's API returns them, read into an Export."""
    missing = [name for name in OBJECTS if name not in objects]
    if missing:
        raise GrocyError(f"the export has no {', '.join(missing)}")
    units = {int(u["id"]): Unit(int(u["id"]), u["name"], u.get("name_plural")) for u in objects["quantity_units"]}
    products = {}
    for p in objects["products"]:
        products[int(p["id"])] = Product(int(p["id"]), p["name"], int(p["qu_id_stock"]), _id(p.get("qu_id_purchase")),
                                         _id(p.get("location_id")), str(p.get("active", 1)) not in ("0", "False", "false"))
    locations = {int(l["id"]): Location(int(l["id"]), l["name"], str(l.get("is_freezer", 0)) in ("1", "True", "true"))
                 for l in objects["locations"]}
    conversions = [Conversion(int(c["from_qu_id"]), int(c["to_qu_id"]), float(c["factor"]), _id(c.get("product_id")))
                   for c in objects["quantity_unit_conversions"]]
    stock = []
    for s in objects["stock"]:
        best = s.get("best_before_date")
        stock.append(StockEntry(int(s["id"]), int(s["product_id"]), float(s["amount"]),
                                _date(s.get("purchased_date") or s.get("row_created_timestamp")),
                                None if not best or str(best)[:10] == NEVER else _date(best),
                                str(s.get("open", 0)) in ("1", "True", "true"), _id(s.get("location_id")),
                                s.get("stock_id") or None, _num(s.get("price"))))
    named = {p.stock_unit for p in products.values()} | {p.purchase_unit for p in products.values()} - {None}
    named |= {u for c in conversions for u in (c.from_unit, c.to_unit)}
    unknown = sorted(named - set(units))
    if unknown:
        raise GrocyError(f"the export names unit ids it does not hold: {unknown}")
    unknown = sorted({s.product for s in stock if s.product not in products})
    if unknown:
        raise GrocyError(f"stock names product ids the export does not hold: {unknown}")
    return Export(units, products, locations, conversions, stock)


def read_export(directory: str) -> Export:
    """An export recorded as one JSON file per REST object (<directory>/<object>.json)."""
    objects = {}
    for name in OBJECTS:
        path = os.path.join(directory, f"{name}.json")
        if not os.path.exists(path):
            raise GrocyError(f"{path}: not found (an export holds {', '.join(OBJECTS)})")
        with open(path, encoding="utf-8") as fh:
            objects[name] = json.load(fh)
    return parse_export(objects)


# -- quantities ------------------------------------------------------------------------------------

def _edges(export: Export, product: int) -> dict[int, dict[int, float]]:
    """The conversions that apply to a product, both ways: {from: {to: factor}}. A product's own
    conversion between two units stands in for a general one between the same two, as in Grocy."""
    edges: dict[int, dict[int, float]] = {}
    for own in (False, True):                  # general first, so the product's own overwrite them
        for c in export.conversions:
            if (c.product == product) != own or (c.product is not None and c.product != product) or not c.factor:
                continue
            edges.setdefault(c.from_unit, {})[c.to_unit] = c.factor
            edges.setdefault(c.to_unit, {})[c.from_unit] = 1 / c.factor
    return edges


def to_kind(export: Export, product: int, unit: int, kind: str) -> tuple[float, int] | None:
    """How many of the nearest unit of `kind` (mass, volume, count) one `unit` of the product is,
    through Grocy's conversions (fewest steps), with that unit's id; None if none is reached."""
    edges = _edges(export, product)
    seen, queue = {unit: 1.0}, deque([unit])
    while queue:
        here = queue.popleft()
        if export.units[here].kind == kind:
            return seen[here], here
        for there, factor in edges.get(here, {}).items():
            if there not in seen:
                seen[there] = seen[here] * factor
                queue.append(there)
    return None


def per_unit(export: Export, product: int, unit: int, kind: str) -> float | None:
    """One `unit` of the product in grams (mass), millilitres (volume) or items (count), or None."""
    found = to_kind(export, product, unit, kind)
    if found is None:
        return None
    factor, target = found
    return factor * UNIT_TABLE[export.units[target].ours][1]


def quantity(export: Export, entry: StockEntry) -> tuple[float, str] | None:
    """A stock entry's amount as this project books it: grams if Grocy's conversions reach a mass,
    else millilitres, else items (which the vocabulary's density or weight per item turns into
    grams when it is booked); None if none of them is reached."""
    unit = export.products[entry.product].stock_unit
    for kind, ours in CANONICAL.items():
        factor = per_unit(export, entry.product, unit, kind)
        if factor is not None:
            return round(entry.amount * factor, 6), ours
    return None


@dataclass(frozen=True)
class Fact:
    """A weight per item, a density or a package's weight that Grocy's conversions state for a product."""
    product: str
    kind: str                   # "each" (g per item), "density" (g per ml) or "package" (g per `unit`)
    grams: float
    unit: str                   # the Grocy unit it is stated for
    general: bool               # True when it rests on a conversion stated for every product


def facts(export: Export) -> list[Fact]:
    """What the conversions say about each product that crosses from a count or volume to a mass."""
    out = []
    for product in sorted(export.products.values(), key=lambda p: p.name.lower()):
        units = {product.stock_unit, product.purchase_unit} - {None}
        units |= {u for c in export.conversions if c.product == product.id for u in (c.from_unit, c.to_unit)}
        density_done = False
        for uid in sorted(units, key=lambda u: export.units[u].name):
            unit = export.units[uid]
            if unit.kind == "mass":
                continue
            grams = per_unit(export, product.id, uid, "mass")
            if grams is None:
                continue
            own = any(c.product == product.id and uid in (c.from_unit, c.to_unit) for c in export.conversions)
            if unit.kind == "count":
                out.append(Fact(product.name, "each", round(grams, 6), unit.name, not own))
            elif unit.kind == "volume":
                if not density_done:
                    out.append(Fact(product.name, "density", round(grams / UNIT_TABLE[unit.ours][1], 6), unit.name, not own))
                    density_done = True
            else:
                out.append(Fact(product.name, "package", round(grams, 6), unit.name, not own))
    return out


# -- the vocabulary and the owner's map ------------------------------------------------------------

@dataclass(frozen=True)
class Vocabulary:
    foods: tuple[str, ...]          # foods a purchase can be: the vocabulary's foods that no food sits under
    groups: frozenset[str]          # the foods others sit under ("Eggs", "Poultry"): not something bought
    each: frozenset[str]            # foods the vocabulary gives a weight per item
    volume: frozenset[str]          # foods the vocabulary gives a density


def read_vocabulary_foods(path: str) -> Vocabulary:
    with open(path, "rb") as fh:
        rows = tomllib.load(fh).get("food", [])
    groups = frozenset(r["parent"] for r in rows if r.get("parent"))
    return Vocabulary(tuple(r["name"] for r in rows if r["name"] not in groups), groups,
                      frozenset(r["name"] for r in rows if r.get("each")),
                      frozenset(r["name"] for r in rows if r.get("volume")))


@dataclass(frozen=True)
class Mapping:
    foods: dict[str, str]           # Grocy product name -> vocabulary food; "" for "not a food here"
    locations: dict[str, str]       # Grocy location name -> Fridge, Freezer or Pantry


def parse_mapping(data: dict) -> Mapping:
    foods, locations = data.get("foods", {}), data.get("locations", {})
    unknown = set(data) - {"foods", "locations"}
    if unknown:
        raise GrocyError(f"the map has sections it does not use: {', '.join(sorted(unknown))}")
    for name, storage in locations.items():
        if storage not in pantry.STORAGE:
            raise GrocyError(f"the map keeps {name!r} in {storage!r}: a storage condition is one of {', '.join(pantry.STORAGE)}")
    for name, food in foods.items():
        if not isinstance(food, str):
            raise GrocyError(f"the map's food for {name!r} is not a name")
    return Mapping(dict(foods), dict(locations))


def read_mapping(path: str | None) -> Mapping:
    if not path:
        return Mapping({}, {})
    with open(path, "rb") as fh:
        return parse_mapping(tomllib.load(fh))


def candidates(name: str, vocabulary: Vocabulary) -> list[str]:
    """Vocabulary foods whose names look like a product's: proposals for the owner, never applied.
    The same name, ignoring case; then a food whose name holds every word of the product's (a
    plural's -s or -es dropped); then difflib's close matches."""
    want = name.strip().lower()
    same = [f for f in vocabulary.foods if f.lower() == want]
    words = [w[:-2] if w.endswith("es") and len(w) > 4 else w[:-1] if w.endswith("s") and len(w) > 3 else w
             for w in want.replace(",", " ").split()]
    holds = [f for f in vocabulary.foods if f not in same and words and all(w in f.lower() for w in words)]
    close = [f for f in difflib.get_close_matches(name, vocabulary.foods, n=3, cutoff=0.75) if f not in same + holds]
    return (same + sorted(holds, key=len) + close)[:5]


def storage_of(location: Location, mapping: Mapping) -> tuple[str | None, str]:
    """A location's storage condition and where it came from; None if the map must name it."""
    if location.name in mapping.locations:
        return mapping.locations[location.name], "the map"
    if location.is_freezer:
        return "Freezer", "Grocy marks it a freezer"
    for storage in pantry.STORAGE:
        if location.name.strip().lower() == storage.lower():
            return storage, "its name"
    return None, "not in the map"


# -- the plan ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PlannedBuy:
    entry: int
    product: str
    food: str
    amount: float
    unit: str
    storage: str
    purchased: date
    opened: bool
    token: str

    def when(self, zone: ZoneInfo) -> datetime:
        """Grocy keeps a date: the purchase is booked at the start of that day where the owner lives."""
        return datetime(self.purchased.year, self.purchased.month, self.purchased.day, tzinfo=zone)

    def portion(self) -> str:
        """The name pantry.buy gives the portion it writes."""
        return f"Purchase {self.token} -- {self.food}"


@dataclass
class Plan:
    matched: dict[str, str] = field(default_factory=dict)              # product -> food, confirmed by the map
    proposed: dict[str, list[str]] = field(default_factory=dict)       # product -> candidates, none confirmed
    not_food: list[str] = field(default_factory=list)                  # products the map says are not foods here
    inactive: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)                  # map entries that cannot be right
    storage: dict[str, tuple[str | None, str]] = field(default_factory=dict)   # location -> (storage, why)
    bookings: list[PlannedBuy] = field(default_factory=list)
    not_booked: list[tuple[int, str, str]] = field(default_factory=list)       # (entry, product, why)
    facts: list[Fact] = field(default_factory=list)
    later: dict[str, int] = field(default_factory=dict)                # what a later stage reads, counted


def token(entry: StockEntry) -> str:
    """The booking's name: Grocy's stock id, which a stock entry keeps through its life."""
    return f"grocy {entry.stock_id}" if entry.stock_id else f"grocy stock {entry.id}"


def plan(export: Export, mapping: Mapping, vocabulary: Vocabulary) -> Plan:
    """What an import of `export` would write, and everything it would not, with why."""
    out = Plan()
    known = set(vocabulary.foods)
    for product in sorted(export.products.values(), key=lambda p: p.name.lower()):
        if not product.active:
            out.inactive.append(product.name)
            continue
        food = mapping.foods.get(product.name)
        if food == "":
            out.not_food.append(product.name)
        elif food is None:
            out.proposed[product.name] = candidates(product.name, vocabulary)
        elif food in vocabulary.groups:
            out.problems.append(f"{product.name}: the map names {food!r}, a group of foods, not a food that is bought")
        else:
            out.matched[product.name] = food
            if food not in known:
                out.problems.append(f"{product.name}: {food!r} is not in the vocabulary file; "
                                    "it must be a food of the instance itself, or the import stops there")
    names = {p.name for p in export.products.values()}
    for name in sorted(set(mapping.foods) - names):
        out.problems.append(f"the map names a product the export does not hold: {name!r}")
    for location in sorted(export.locations.values(), key=lambda l: l.name.lower()):
        out.storage[location.name] = storage_of(location, mapping)
    for entry in export.stock:
        product = export.products[entry.product]
        why = None
        if not product.active:
            why = "the product is not active in Grocy"
        elif product.name in out.not_food:
            why = "not a food here (the map)"
        elif product.name not in out.matched:
            why = "no food confirmed for it in the map"
        location = export.locations.get(entry.location if entry.location is not None else product.location)
        storage = storage_of(location, mapping)[0] if location else None
        if why is None and storage is None:
            why = (f"no storage condition for {location.name!r} in the map" if location
                   else "no location, and none for the product")
        amount = quantity(export, entry)
        if why is None and amount is None:
            unit = export.units[product.stock_unit]
            why = f"{entry.amount:g} {unit.name} does not convert to a mass, a volume or items in Grocy's conversions"
        if why is None and entry.purchased is None:
            why = "no purchase date"
        if why is None and entry.amount <= 0:
            why = "an amount of 0"
        if why:
            out.not_booked.append((entry.id, product.name, why))
            continue
        out.bookings.append(PlannedBuy(entry.id, product.name, out.matched[product.name], amount[0], amount[1],
                                       storage, entry.purchased, entry.opened, token(entry)))
    out.facts = facts(export)
    out.later = {"best-before dates": sum(1 for s in export.stock if s.best_before),
                 "prices": sum(1 for s in export.stock if s.price)}
    return out


def draft_map(export: Export, vocabulary: Vocabulary, mapping: Mapping) -> str:
    """A map file for the owner to review: what the map says already, each product with a food of
    the same name filled in, every other one commented out with its candidates, and each location
    the importer cannot place. Nothing in it is confirmed until the owner saves it as the map."""
    lines = ["# A draft for review (docs/imports.md). A line that is not commented out is a match the importer",
             "# will use: check each one. \"\" means the product is not a food here.", "[foods]"]
    for product in sorted(export.products.values(), key=lambda p: p.name.lower()):
        if not product.active:
            continue
        if product.name in mapping.foods:
            lines.append(f"{json.dumps(product.name)} = {json.dumps(mapping.foods[product.name])}")
            continue
        found = candidates(product.name, vocabulary)
        if found and found[0].lower() == product.name.lower():
            lines.append(f"{json.dumps(product.name)} = {json.dumps(found[0])}      # the same name: check it")
        else:
            lines.append(f"# {json.dumps(product.name)} = " + (" or ".join(json.dumps(f) for f in found) if found else '""')
                         + ("" if found else "      # nothing alike in the vocabulary: a new food to add, or not a food"))
    lines += ["", "[locations]"]
    for location in sorted(export.locations.values(), key=lambda l: l.name.lower()):
        storage, why = storage_of(location, mapping)
        if why == "the map":
            lines.append(f"{json.dumps(location.name)} = {json.dumps(storage)}")
        elif storage is None:
            lines.append(f"# {json.dumps(location.name)} = \"Fridge\" or \"Freezer\" or \"Pantry\"")
    return "\n".join(lines) + "\n"


# -- booking ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Booked:
    buy: PlannedBuy
    created: int                    # nodes written: 0 when it was booked before
    problem: str | None = None


def book(client, the_plan: Plan, zone: ZoneInfo) -> list[Booked]:
    """Book each planned purchase through pantry.buy, and open what Grocy has opened. A purchase the
    instance refuses (a food it does not have, an amount it cannot weigh) is reported, and the rest go on."""
    out = []
    for item in the_plan.bookings:
        try:
            booking = pantry.buy(client, item.food, item.amount, item.unit, item.when(zone), item.token,
                                 storage=item.storage)
            created = len(booking.created)
            if item.opened:
                rows = [r for r in client.get("/structr/rest/PortionOfSubstance", params={"name": item.portion()})["result"]
                        if r.get("name") == item.portion()]
                if len(rows) != 1:
                    raise pantry.PantryError(f"{item.portion()}: expected one portion after the purchase, found {len(rows)}")
                pantry.open_portion(client, rows[0]["id"])
            out.append(Booked(item, created))
        except (pantry.PantryError, LookupError) as exc:
            out.append(Booked(item, 0, str(exc)))
    return out
