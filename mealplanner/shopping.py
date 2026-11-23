"""A week's shopping list: what its committed meals need that the pantry does not hold.

data-model.md Sec 7's AcquisitionList, computed and never stored: the amounts are
reservation.acquisition()'s (net_requirements), what the week's committed, not yet cooked meals
call for, scaled by servings planned over the recipe's yield, plus any StockPolicy target, less
eligible stock on hand. This adds what a list for a person needs: each food's name, the day it is
first needed (so perishables can wait for a later trip), the recipes that use it, a count where the
food has a weight per item, an estimated cost at a price level (mealplanner/prices.py), what the
pantry already covers, and the ingredients a recipe gives no amount for ("salt to taste"), which
no arithmetic can put on a list.

With a package level (mealplanner/packages.py), what to buy is rounded up to what the food is sold
in: the packages that leave least over, and what will be left of them beyond what the week uses, its
cost, and until when it keeps (left_over). A food the recipes count and no level gives a size is
bought in whole items; anything else is bought as much as is needed. The cost is of what is bought.

Known limits, as the model's: amounts are in the form the recipe needs them, not the form bought
(net_requirements' note on trimming; docs/todo.md, "What ingredients are sold in", stage 3). Leftover
meals add nothing: they eat what an earlier cook made.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mealplanner.defaults import resolve_default
from mealplanner.inventory import _type_or_none, assumed_storage, shelf_life_days
from mealplanner.material_accounting import plan_specifications
from mealplanner.nutrition_scope import entry_start
from mealplanner.packages import choose, food_packages
from mealplanner.prices import food_price
from mealplanner.reservation import acquisition, resolve_stock_policy
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from structr_client import ReadCache

GRAMS_PER_LB = 453.592
GRAMS_PER_OZ = 28.3495
LEFT_G = 0.5                    # less than this left over is nothing left (pantry.USED_UP_G)
SHORT_G = 1e-3                  # less than this short is rounding (a draw is stored to a millionth of a gram), not a purchase


def _grams_text(grams: float) -> str:
    if grams >= GRAMS_PER_LB / 2:
        return f"{grams:,.0f} g ({grams / GRAMS_PER_LB:.1f} lb)"
    if grams >= GRAMS_PER_OZ:
        return f"{grams:,.0f} g ({grams / GRAMS_PER_OZ:.1f} oz)"
    return f"{grams:,.0f} g"


@dataclass
class Line:
    food: str
    buy: float                      # grams to buy
    need: float                     # grams the meals call for
    have: float                     # grams of eligible stock on hand
    target: float = 0.0             # a StockPolicy's level kept in stock, grams
    first_needed: datetime | None = None
    recipes: list[str] = field(default_factory=list)
    optional: bool = False          # every use of it is optional
    each: float | None = None       # grams per item, where the recipes count the food (eggs, tortillas)
    cost: float | None = None       # dollars for what is bought (`bought`), at the price level
    estimated_price: bool = False
    packages: list[tuple[int, str]] = field(default_factory=list)   # (how many, of which size), what is bought
    estimated_size: bool = False    # a package size rests on an estimate (the public level's)
    bought: float | None = None     # grams bought: whole packages or items; None until worked out
    left: float = 0.0               # grams of it left over beyond what the week uses (and a policy keeps)
    left_cost: float | None = None  # dollars of what is left over
    keeps_until: datetime | None = None   # when what is left over is past its shelf life
    keeps_opened: bool = False      # ...as an opened package (else unopened); both from its first use

    def amount(self) -> str:
        if self.packages:
            sizes = " + ".join(f"{n} x {label}" for n, label in self.packages)
            return f"{sizes} (about {self.bought:,.0f} g)"
        grams = self.buy if self.buy > 0 else self.need
        if self.each:
            count = math.ceil(grams / self.each - 1e-9)
            return f"{count} (about {self.bought or grams:,.0f} g)"
        return _grams_text(grams)


@dataclass
class ShoppingList:
    week: str
    cooks: int
    leftovers: int
    to_buy: list[Line]
    covered: list[Line]
    unquantified: dict[str, list[str]]          # food -> the recipes that give no amount for it
    unpriced: list[str] = field(default_factory=list)
    not_bought: list[str] = field(default_factory=list)     # priced at nothing: tap water

    @property
    def total(self) -> float:
        return sum(line.cost or 0.0 for line in self.to_buy)

    @property
    def left_total(self) -> float:
        return sum(line.left_cost or 0.0 for line in self.to_buy)


def _pool_root(client, type_id: str) -> str:
    resolution = resolve_stock_policy(client, type_id)
    return resolution.root_type_id if resolution else type_id


def keeps_days(client, food_id: str) -> tuple[float | None, bool]:
    """(how many days what is left of a food keeps from its first use, whether that is as opened): of
    the fridge and the pantry, the longest a FoodKeeper figure for it opened gives. A food with no
    opened figure keeps as it does unopened, where the pantry assumes it is kept
    (inventory.assumed_storage); neither, None. An opened can of beans keeps days in the fridge, not
    its unopened years in the pantry. The planner weighs package waste with the same figure
    (planning/extract.py, model.Packaging)."""
    kind, opened = _type_or_none(client, "ShelfLife"), _type_or_none(client, "Opened")
    if kind is None or opened is None:
        return None, False
    best = None
    for storage in ("Fridge", "Pantry"):
        where = _type_or_none(client, storage)
        found = resolve_default(client, food_id, kind, {where, opened}) if where else None
        if found is not None and opened in found.keyed_by and found.quantity.get("value") is not None \
                and (best is None or found.quantity["value"] > best):
            best = found.quantity["value"]
    if best is not None:
        return float(best), True
    days = shelf_life_days(client, food_id, "Sealed", assumed_storage(client, {"instanceOf": {"id": food_id}}))
    return (float(days), False) if days is not None else (None, False)


def left_over_keeps(client, food_id: str, first_use: datetime) -> tuple[datetime | None, bool]:
    """(until when what is left of a food keeps, whether that is as opened): keeps_days from its first
    use, as if bought then, which a list grouped by the day each food is first needed allows: bought
    earlier, it keeps less long."""
    days, opened = keeps_days(client, food_id)
    return (first_use + timedelta(days=days), opened) if days is not None else (None, False)


def _round_up(client, line: Line, root: str, packages: dict | None) -> None:
    """Set what is bought of a line to buy: whole packages of the sizes its food is sold in (choose),
    or whole items for a food the recipes count, or as much as is needed."""
    sizes = []
    for p in (food_packages(client, packages, root) if packages is not None else ()):
        grams = convert_to_grams(client, root, p.amount, p.unit)
        if grams:
            sizes.append((grams, p))
    if sizes:
        counts = choose([g for g, _ in sizes], line.buy)
        line.packages = [(n, p.label) for n, (_, p) in zip(counts, sizes) if n]
        line.estimated_size = any(p.estimated for n, (_, p) in zip(counts, sizes) if n)
        line.bought = sum(n * g for n, (g, _) in zip(counts, sizes))
    elif line.each:
        line.bought = math.ceil(line.buy / line.each - 1e-9) * line.each
    else:
        line.bought = line.buy
    line.left = max(0.0, line.bought - line.buy)


def shopping_list(client, meal_plan_id: str, now: datetime, prices: dict | None = None,
                  packages: dict | None = None) -> ShoppingList:
    """The list for a MealPlan's committed meals as of `now`; `prices` is prices.price_table(),
    `packages` packages.package_table()."""
    client = ReadCache(client)
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    details: dict[str, dict] = {}
    unquantified: dict[str, list[str]] = {}
    cooks = leftovers = 0
    for ref in meal_plan.get("hasEntry", []):
        entry = client.get_all("MealPlanEntry", ref["id"])["result"]
        if entry.get("isSkipped") or entry.get("fulfilledBy"):
            continue
        if not entry.get("references") or entry.get("hasPlannedServings") is None:
            leftovers += 1
            continue
        cooks += 1
        plan = client.get_all("Plan", entry["references"]["id"])["result"]
        start = entry_start(client, entry)
        specs = plan_specifications(client, plan)
        produced = {s["specifies"]["id"] for s in specs if s.get("hasParticipationRole") == "output" and s.get("specifies")}
        for spec in specs:
            food = spec.get("specifies")
            if spec.get("hasParticipationRole") != "input" or not food or food["id"] in produced:
                continue
            qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"] \
                if spec.get("hasSpecifiedQuantity") else {}
            grams = (convert_to_grams(client, food["id"], qty["value"], qty.get("unit"))
                     if qty.get("value") is not None else None)
            if not grams:
                used_by = unquantified.setdefault(food.get("name") or food["id"], [])
                if plan["name"] not in used_by:
                    used_by.append(plan["name"])
                continue
            d = details.setdefault(_pool_root(client, food["id"]), {"recipes": [], "first": None, "optional": True,
                                                                   "counted": False})
            d["counted"] = d["counted"] or UNIT_TABLE.get(str(qty.get("unit") or "").strip().lower(), ("",))[0] == "count"
            if plan["name"] not in d["recipes"]:
                d["recipes"].append(plan["name"])
            if start is not None and (d["first"] is None or start < d["first"]):
                d["first"] = start
            d["optional"] = d["optional"] and bool(spec.get("isOptional"))
    to_buy, covered, unpriced, not_bought = [], [], [], []
    for root, need in acquisition(client, meal_plan_id, now).items():
        if need.demand <= 0 and need.net <= 0:
            continue                               # a policy's pool with nothing to do this week
        d = details.get(root, {"recipes": [], "first": None, "optional": False, "counted": False})
        name = client.get_all("DomainType", root)["result"].get("name") or root
        each = convert_to_grams(client, root, 1, "each") if d["counted"] else None
        buy = need.net if need.net >= SHORT_G else 0.0
        line = Line(name, buy, need.demand, need.eligible, need.target, d["first"], d["recipes"], d["optional"], each)
        if line.buy > 0:
            price = food_price(client, prices, root) if prices is not None else None
            if price is not None and price.quantity.get("value") == 0:
                not_bought.append(name)                # a price of nothing: not something to shop for
                continue
            _round_up(client, line, root, packages)
            if line.left >= LEFT_G:
                line.keeps_until, line.keeps_opened = left_over_keeps(client, root, d["first"] or now)
            if price is not None and price.quantity.get("value") is not None:
                line.cost = line.bought * price.quantity["value"] / 100.0
                line.left_cost = line.left * price.quantity["value"] / 100.0
                line.estimated_price = (price.spec or {}).get("provenance") == "estimated"
            elif prices is not None:
                unpriced.append(name)
            to_buy.append(line)
        else:
            covered.append(line)
    for food in list(unquantified):
        if any(line.food == food for line in to_buy + covered) or food in not_bought:
            del unquantified[food]                 # some recipe gives it an amount: it is on the list already
    covered.sort(key=lambda line: line.food)
    return ShoppingList(meal_plan.get("name") or meal_plan_id, cooks, leftovers, to_buy, covered, unquantified,
                        sorted(unpriced), sorted(not_bought))


def left_over_text(line: Line, zone) -> str:
    """What will be left of a line's purchase, in words, or "" when nothing is."""
    if line.left < LEFT_G:
        return ""
    cost = "" if line.left_cost is None else f" (${line.left_cost:,.2f})"
    if line.keeps_until is None:
        keeps = "; no shelf life known"
    else:
        keeps = f"; keeps to {line.keeps_until.astimezone(zone).strftime('%a %d %b %Y')}" + (" once opened" if line.keeps_opened else " unopened")
    return f"{_grams_text(line.left)} left over{cost}{keeps}"


def describe(shopping: ShoppingList, zone, level: str | None = None, package_level: str | None = None) -> str:
    """The list in words, grouped by the day each food is first needed (in `zone`)."""
    sizes = (f"rounded up to what is sold, at {package_level!r} (+ a size rests on an estimate)" if package_level
             else "amounts are what the recipes use, not package sizes")
    lines = [f"Shopping list for {shopping.week}: {shopping.cooks} meals to cook, {shopping.leftovers} of leftovers "
             f"(which need nothing more).",
             f"What the meals call for, less what the pantry holds; {sizes}."]
    day = None
    width = max((len(line.food) for line in shopping.to_buy), default=0)
    by_day = sorted(shopping.to_buy, key=lambda line: (line.first_needed is None,
                                                       line.first_needed.astimezone(zone).date() if line.first_needed else None,
                                                       line.food))
    for line in by_day:
        first = line.first_needed.astimezone(zone).strftime("%a %d %b") if line.first_needed else "no day set"
        if first != day:
            lines.append(f"\nFirst needed {first}:")
            day = first
        cost = "" if line.cost is None else f"${line.cost:,.2f}{'*' if line.estimated_price else ''}"
        extra = []
        if line.have > 0:
            extra.append(f"have {line.have:,.0f} g of {line.need + line.target:,.0f} g")
        if line.target > 0:
            extra.append(f"keeps {line.target:,.0f} g in stock")
        if line.optional:
            extra.append("optional")
        extra.append(", ".join(line.recipes) if line.recipes else "the pantry's level")
        amount = line.amount() + ("+" if line.estimated_size else "")
        lines.append(f"  {line.food:<{width}}  {amount:<24} {cost:>8}   {'; '.join(extra)}")
        left = left_over_text(line, zone)
        if left:
            lines.append(f"  {'':<{width}}  {left}")
    if level:
        left = f", of which ${shopping.left_total:,.2f} is left over" if shopping.left_total >= 0.005 else ""
        lines.append(f"\nAbout ${shopping.total:,.2f} at {level!r}{left}" + (" (* priced from an estimate)" if any(
            line.estimated_price for line in shopping.to_buy) else "")
                     + (f"; not priced: {', '.join(shopping.unpriced)}" if shopping.unpriced else ""))
    if shopping.not_bought:
        lines.append("\nNot bought: " + ", ".join(shopping.not_bought))
    if shopping.covered:
        lines.append("\nThe pantry covers: " + ", ".join(f"{line.food} ({line.need:,.0f} of {line.have:,.0f} g)"
                                                          for line in shopping.covered))
    if shopping.unquantified:
        lines.append("\nNo amount in the recipe, so check there is some: " + ", ".join(
            f"{food} ({', '.join(recipes)})" for food, recipes in sorted(shopping.unquantified.items())))
    return "\n".join(lines)
