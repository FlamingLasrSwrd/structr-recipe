"""Prices: public figures per food as defaults, the owner's own, and what a recipe costs (data-model.md J27).

A price is a DefaultSpecification of kind "Unit Price" on a Type in the "Price Reference"
hierarchy, keyed by a food Type and valued in dollars per 100 g of the food as a recipe
weighs it (QuantitySpecification unit USD_per_100g). data/prices.toml says where each comes
from; the levels, each a child of the one before, are:

  US prices 2017-18 adjusted (Purchase to Plate)   USDA ERS PP-NAP 2017-18 prices, brought
                                                   forward by the CPI for food at home
    US prices (BLS)                                the BLS average price, U.S. city average
      West prices (BLS)                            the West region's, where BLS publishes it

and, below whichever the owner chooses, the owner's own level (instantiate_prices, from
private/prices.toml), whose prices are theirs. Resolution is the profiles' (defaults.resolve_all):
the nearest level with a price for a food wins, so a current BLS price overrides an adjusted
2017-18 one and the owner's own overrides both. A food with no price takes the nearest
ancestor food's (Butter (salted) -> Butter).

A recipe's cost is computed, never stored: its raw, non-optional ingredients (the ones
nutrition counts, nutrition_scope.raw_inputs) in grams, times their price, over its
servings. An ingredient with no price or no weight is left out and named, so the cost is
what is known, not a guess at the rest.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field

from mealplanner.defaults import resolve_all
from mealplanner.nutrition_scope import _input_grams, raw_inputs
from mealplanner.profiles import ProfileError, Report, _name_ok, _one_id, food_types
from mealplanner.typetree import ancestors_or_self
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from mealplanner.vocabulary_import import Sync
from structr_client import ReadCache

PRICES = "data/prices.toml"
BLS_PIN = "data/prices/bls.json"
PPNAP_PIN = "data/prices/ppnap.json"
PRICE_HIERARCHY = "Price Reference"
PRICE_KIND = "Unit Price"
PRICE_UNIT = "USD_per_100g"
PPNAP_LEVEL = "US prices 2017-18 adjusted (Purchase to Plate)"
US_LEVEL = "US prices (BLS)"
WEST_LEVEL = "West prices (BLS)"
LEVELS = ((PPNAP_LEVEL, None), (US_LEVEL, PPNAP_LEVEL), (WEST_LEVEL, US_LEVEL))
AREAS = {US_LEVEL: ("US", "0000", "U.S. city average"), WEST_LEVEL: ("West", "0400", "West region")}


# -- the file ----------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    food: str
    bls: str | None = None          # a BLS average price item code, like "701111"
    ppnap: str | None = None        # an FNDDS food code in Purchase to Plate
    proxy: bool = False             # the source prices a similar food, not this one
    cooked: bool = False            # a Purchase to Plate price for the cooked food, used for the raw one
    free: bool = False              # costs nothing worth counting (tap water)
    note: str = ""


@dataclass(frozen=True)
class Book:
    bls_items: dict                 # code -> (name, per amount, per unit)
    entries: tuple[Entry, ...]


def parse_prices(data: dict) -> Book:
    """data/prices.toml, or ProfileError naming every problem."""
    problems: list[str] = []
    items = {}
    for code, item in data.get("bls", {}).items():
        per = item.get("per")
        if not item.get("name") or not isinstance(per, list) or len(per) != 2 \
                or not isinstance(per[0], (int, float)) or isinstance(per[0], bool) or per[0] <= 0 \
                or per[1] not in UNIT_TABLE:
            problems.append(f"bls item {code!r}: give a name and per = [amount above 0, unit], a unit the unit table knows")
            continue
        items[code] = (item["name"], float(per[0]), per[1])
    entries, seen = [], set()
    for i, raw in enumerate(data.get("price", []), 1):
        where = f"price {i}"
        if not _name_ok(where, raw.get("food"), problems):
            continue
        where = f"price {i} ({raw['food']!r})"
        unknown = set(raw) - {"food", "bls", "ppnap", "proxy", "cooked", "free", "note"}
        if unknown:
            problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
        if raw["food"] in seen:
            problems.append(f"{where}: listed twice")
        seen.add(raw["food"])
        bls, ppnap, free = raw.get("bls"), raw.get("ppnap"), bool(raw.get("free"))
        if free and (bls or ppnap):
            problems.append(f"{where}: a free food names no source")
        if not free and not (bls or ppnap):
            problems.append(f"{where}: name a source (bls, ppnap) or say free = true")
        if bls is not None and bls not in items:
            problems.append(f"{where}: bls item {bls!r} is not in [bls]")
        if raw.get("cooked") and not ppnap:
            problems.append(f"{where}: cooked is for a Purchase to Plate price")
        entries.append(Entry(raw["food"], bls, None if ppnap is None else str(ppnap), bool(raw.get("proxy")),
                             bool(raw.get("cooked")), free, raw.get("note", "")))
    if problems:
        raise ProfileError(problems)
    return Book(items, tuple(entries))


def read_book(root: str) -> tuple[Book, dict, dict]:
    """(the price file, the pinned BLS figures, the pinned Purchase to Plate figures)."""
    with open(os.path.join(root, PRICES), "rb") as fh:
        book = parse_prices(tomllib.load(fh))
    with open(os.path.join(root, BLS_PIN)) as fh:
        bls = json.load(fh)
    with open(os.path.join(root, PPNAP_PIN)) as fh:
        ppnap = json.load(fh)
    return book, bls, ppnap


# -- what each level says ------------------------------------------------------

@dataclass(frozen=True)
class LevelPrice:
    level: str
    food: str
    price: float                    # dollars
    per: tuple[float, str]          # for this much of the food
    status: str                     # sourced, calculated or estimated
    source: str


def cpi_ratio(bls: dict) -> float:
    cpi = bls["cpi"]
    return cpi["latest"]["value"] / cpi["base"]["value"]


def level_prices(book: Book, bls: dict, ppnap: dict) -> tuple[list[LevelPrice], list[str]]:
    """Every price each level states, and what the pins lack. Pure: no conversion to grams yet."""
    out, problems = [], []
    ratio, cpi = cpi_ratio(bls), bls["cpi"]
    for e in book.entries:
        note = f"; {e.note}" if e.note else ""
        if e.free:
            out.append(LevelPrice(PPNAP_LEVEL, e.food, 0.0, (100.0, "g"), "estimated", f"free{note}"))
            continue
        if e.ppnap:
            food = ppnap["foods"].get(e.ppnap)
            if food is None:
                problems.append(f"{e.food!r}: FNDDS {e.ppnap} is not in {PPNAP_PIN} (tools/price_extract.py)")
            else:
                status = "estimated" if e.proxy or e.cooked else "calculated"
                cooked = "; priced as cooked, which overstates a raw gram" if e.cooked else ""
                proxy = " (a similar food)" if e.proxy else ""
                out.append(LevelPrice(PPNAP_LEVEL, e.food, food["price_100g"] * ratio, (100.0, "g"), status,
                                      f"USDA ERS Purchase to Plate {ppnap['year']}, FNDDS {e.ppnap} {food['description']}"
                                      f"{proxy}: ${food['price_100g']:.3f} per 100 g edible x {ratio:.4f} (CPI "
                                      f"{cpi['series']} {cpi['latest']['period']} {cpi['latest']['value']:g} over "
                                      f"{cpi['base']['period']} {cpi['base']['value']:.3f}){cooked}{note}"))
        if e.bls:
            name, amount, unit = book.bls_items[e.bls]
            figures = bls["items"].get(e.bls, {})
            if "US" not in figures:
                problems.append(f"{e.food!r}: BLS item {e.bls} has no U.S. price in {BLS_PIN} (tools/price_extract.py)")
            for level, (key, area, label) in AREAS.items():
                figure = figures.get(key)
                if figure is None:
                    continue
                proxy = " (a similar food)" if e.proxy else ""
                out.append(LevelPrice(level, e.food, figure["value"], (amount, unit),
                                      "estimated" if e.proxy else "sourced",
                                      f"BLS average price APU{area}{e.bls} {name}{proxy}, {label}, {figure['period']}: "
                                      f"${figure['value']:.3f} per {amount:g} {unit}{note}"))
    return out, problems


# -- loading ---------------------------------------------------------------------

def _per_100g(client, food_id: str, food: str, price: float, per: tuple[float, str], problems: list) -> float | None:
    grams = convert_to_grams(client, food_id, per[0], per[1])
    if not grams:
        problems.append(f"{food!r}: {per[0]:g} {per[1]} does not convert to grams (no density or weight per item)")
        return None
    return price / grams * 100.0


def import_prices(client, book: Book, bls: dict, ppnap: dict) -> dict[str, int]:
    """Write the three public levels (idempotent). A price the file no longer names is
    removed. The vocabulary must be loaded first: foods are looked up, never created."""
    prices, problems = level_prices(book, bls, ppnap)
    foods = food_types(client)
    rows = []
    for lp in prices:
        if lp.food not in foods:
            problems.append(f"{lp.food!r} is not a food in the vocabulary")
            continue
        value = _per_100g(client, foods[lp.food], lp.food, lp.price, lp.per, problems)
        rows.append((lp, value))
    if problems:
        raise ProfileError(sorted(set(problems)))

    sync = Sync(client)
    hierarchy = sync.ensure("TypeHierarchy", PRICE_HIERARCHY, {"singleParent": True})
    kind = sync.ensure("DomainType", PRICE_KIND, {"hierarchy": _one_id(client, "TypeHierarchy", "Default Kind")})
    ids: dict[str, str] = {}
    for level, parent in LEVELS:
        ids[level] = sync.ensure("DomainType", level, {"hierarchy": hierarchy, "isLookupBearing": True,
                                                       "parent": ids[parent] if parent else None})
    written = set()
    for lp, value in rows:
        label = f"{lp.level} -- {lp.food}"
        qty = sync.ensure("QuantitySpecification", f"{label} price", {
            "value": round(value, 6), "unit": PRICE_UNIT, "status": "default"})
        sync.ensure("DefaultSpecification", label, {
            "forType": ids[lp.level], "hasKind": kind, "hasValue": qty, "keyedBy": [foods[lp.food]],
            "provenance": lp.status, "source": f"{lp.source} = ${value:.4f} per 100 g"})
        written.add(label)
    for level, _ in LEVELS:
        _prune(client, sync, ids[level], kind, written)
    return sync.counts


def _prune(client, sync: Sync, level_id: str, kind_id: str, keep: set) -> list[str]:
    """Remove the prices of kind Unit Price on a level that are not in `keep`."""
    removed = []
    for ref in client.get_all("DomainType", level_id)["result"].get("defaultSpecifications", []):
        spec = client.get_all("DefaultSpecification", ref["id"])["result"]
        if (spec.get("hasKind") or {}).get("id") != kind_id or spec["name"] in keep:
            continue
        value = spec.get("hasValue")
        sync.delete("DefaultSpecification", spec)
        if value:
            sync.delete("QuantitySpecification", client.get_all("QuantitySpecification", value["id"])["result"])
        removed.append(spec["name"])
    return removed


# -- the owner's own prices -----------------------------------------------------

def instantiate_prices(client, selection: dict) -> Report:
    """The owner's price level from their selection file:

        name = "Home prices"
        profile = "West prices (BLS)"          # the public level to fall back on
        [own]                                  # what the owner pays
        "Olive oil" = { price = 11.99, amount = 16.9, unit = "fl_oz", note = "Costco, 2026-09" }

    The level is a Type below the chosen one, so its prices win and every other food
    falls back to the public figures. An owner's price is `specified` and `sourced`,
    and names the file. One the file no longer has is removed."""
    report = Report()
    problems: list[str] = []
    name = selection.get("name", "Home prices")
    if not _name_ok("name", name, problems):
        raise ProfileError(problems)
    if name in {level for level, _ in LEVELS}:
        raise ProfileError([f"name: {name!r} is a public level; give the owner's level its own name"])
    parent = _one_id(client, "DomainType", selection.get("profile", ""))
    kind = _one_id(client, "DomainType", PRICE_KIND)
    if parent is None or kind is None:
        raise ProfileError([f"no price level {selection.get('profile')!r} (load the prices with tools/import_prices.py)"])
    foods = food_types(client)
    own = []
    for food, p in selection.get("own", {}).items():
        where = f"own {food!r}"
        if food not in foods:
            problems.append(f"{where}: not a food in the vocabulary")
            continue
        price, amount, unit = p.get("price"), p.get("amount"), p.get("unit")
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0 \
                or not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0 \
                or not isinstance(unit, str) or unit not in UNIT_TABLE:
            problems.append(f"{where}: give price (0 or more), amount (above 0) and a unit the unit table knows")
            continue
        value = _per_100g(client, foods[food], food, float(price), (float(amount), unit), problems)
        if value is not None:
            own.append((food, float(price), float(amount), unit, value, p.get("note", "")))
    if problems:
        raise ProfileError(problems)

    sync = Sync(client)
    hierarchy = _one_id(client, "TypeHierarchy", PRICE_HIERARCHY)
    level = sync.ensure("DomainType", name, {"hierarchy": hierarchy, "isLookupBearing": True, "parent": parent})
    written = set()
    for food, price, amount, unit, value, note in own:
        label = f"{name} -- {food}"
        qty = sync.ensure("QuantitySpecification", f"{label} price", {
            "value": round(value, 6), "unit": PRICE_UNIT, "status": "specified"})
        sync.ensure("DefaultSpecification", label, {
            "forType": level, "hasKind": kind, "hasValue": qty, "keyedBy": [foods[food]], "provenance": "sourced",
            "source": f"the owner's price (private/prices.toml): ${price:g} for {amount:g} {unit}"
                      + (f"; {note}" if note else "") + f" = ${value:.4f} per 100 g"})
        written.add(label)
        report.written.append(label)
    report.removed = _prune(client, sync, level, kind, written)
    report.counts = sync.counts
    return report


# -- what things cost ----------------------------------------------------------------

def price_table(client, level_name: str) -> dict[str, dict]:
    """Food Type id -> the resolved Unit Price default (ResolvedDefault) seen from a level."""
    level = _one_id(client, "DomainType", level_name)
    kind = _one_id(client, "DomainType", PRICE_KIND)
    if level is None or kind is None:
        raise ProfileError([f"no price level {level_name!r}"])
    table = {}
    for keys, default in resolve_all(client, level, kind).items():
        (food_id,) = keys
        table[food_id] = default
    return table


def food_price(client, table: dict, food_id: str):
    """The price of a food, or of its nearest ancestor food that has one; None if none has."""
    for type_id in ancestors_or_self(client, food_id):
        if type_id in table:
            return table[type_id]
    return None


@dataclass
class RecipeCost:
    per_serving: float              # dollars, over the ingredients that could be priced
    unpriced: list[str] = field(default_factory=list)    # no price, or no weight to price
    estimated: list[str] = field(default_factory=list)   # priced from an estimate


def recipe_cost(client, plan: dict, table: dict, servings: float) -> RecipeCost:
    """What one serving of a Plan costs in ingredients, from `table` (price_table)."""
    total, cost = 0.0, RecipeCost(0.0)
    for _, spec in raw_inputs(client, plan):
        food = spec["specifies"]
        name = food.get("name") or food["id"]
        price = food_price(client, table, food["id"])
        grams = _input_grams(client, spec, food["id"]) if price is not None else None
        if price is None or grams is None:
            if name not in cost.unpriced:
                cost.unpriced.append(name)
            continue
        total += grams * price.quantity["value"] / 100.0
        if price.quantity["value"] and (price.spec or {}).get("provenance") == "estimated" and name not in cost.estimated:
            cost.estimated.append(name)
    cost.per_serving = total / servings
    return cost


def describe_cost(client, problem, evaluation, level: str, days: int) -> str:
    """The week's cost in words: what the meals it cooks cost, a day's average, each recipe's
    cost a serving, and what could not be priced. A cook costs its servings cooked, so
    leftovers cost nothing more; a meal already committed counts like a proposed one."""
    client = ReadCache(client)          # read-only: each node is fetched once for the whole report
    table = price_table(client, level)
    details = {d["slot"]: d for d in evaluation.slot_details}
    costs: dict[str, tuple[str, RecipeCost]] = {}
    total = 0.0
    for slot, pick in zip(problem.slots, evaluation.picks):
        d = details.get(slot.key)
        if d is None or d["kind"] != "cook" or pick.candidate is None:
            continue
        candidate = problem.candidates[pick.candidate]
        if candidate.id not in costs:
            plan = client.get_all("Plan", candidate.id)["result"]
            costs[candidate.id] = (candidate.name, recipe_cost(client, plan, table, candidate.yield_servings))
        total += costs[candidate.id][1].per_serving * d["cooked_servings"]
    lines = [f"Cost, at the prices seen from {level!r}: about ${total:.2f} for the meals this week cooks, "
             f"${total / max(days, 1):.2f} a day"]
    for name, cost in sorted(costs.values(), key=lambda kv: (-kv[1].per_serving, kv[0])):
        missing = f" ({len(cost.unpriced)} ingredient{'s' if len(cost.unpriced) != 1 else ''} not priced)" if cost.unpriced else ""
        lines.append(f"  {name}: ${cost.per_serving:.2f} a serving{missing}")
    unpriced = sorted({n for _, c in costs.values() for n in c.unpriced})
    if unpriced:
        lines.append("  not priced, so left out: " + ", ".join(unpriced))
    estimated = sorted({n for _, c in costs.values() for n in c.estimated})
    if estimated:
        lines.append("  priced from an estimate (a similar food, or a cooked price): " + ", ".join(estimated))
    return "\n".join(lines)
