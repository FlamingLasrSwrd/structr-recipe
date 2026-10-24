"""A week's shopping list: what its committed meals need that the pantry does not hold.

data-model.md Sec 7's AcquisitionList, computed and never stored: the amounts are
reservation.acquisition()'s (net_requirements), what the week's committed, not yet cooked meals
call for, scaled by servings planned over the recipe's yield, plus any StockPolicy target, less
eligible stock on hand. This adds what a list for a person needs: each food's name, the day it is
first needed (so perishables can wait for a later trip), the recipes that use it, a count where the
food has a weight per item, an estimated cost at a price level (mealplanner/prices.py), what the
pantry already covers, and the ingredients a recipe gives no amount for ("salt to taste"), which
no arithmetic can put on a list.

Known limits, as the model's: amounts are what recipes use, not package sizes (data-model.md J24
(5)), and in the form the recipe needs them (net_requirements' note on trimming). Leftover meals
add nothing: they eat what an earlier cook made.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.material_accounting import plan_specifications
from mealplanner.nutrition_scope import entry_start
from mealplanner.prices import food_price
from mealplanner.reservation import acquisition, resolve_stock_policy
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from structr_client import ReadCache

GRAMS_PER_LB = 453.592
GRAMS_PER_OZ = 28.3495


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
    cost: float | None = None       # dollars for `buy`, at the price level
    estimated_price: bool = False

    def amount(self) -> str:
        grams = self.buy if self.buy > 0 else self.need
        if self.each:
            count = math.ceil(grams / self.each - 1e-9)
            return f"{count} (about {grams:,.0f} g)"
        if grams >= GRAMS_PER_LB / 2:
            return f"{grams:,.0f} g ({grams / GRAMS_PER_LB:.1f} lb)"
        if grams >= GRAMS_PER_OZ:
            return f"{grams:,.0f} g ({grams / GRAMS_PER_OZ:.1f} oz)"
        return f"{grams:,.0f} g"


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


def _pool_root(client, type_id: str) -> str:
    resolution = resolve_stock_policy(client, type_id)
    return resolution.root_type_id if resolution else type_id


def shopping_list(client, meal_plan_id: str, now: datetime, prices: dict | None = None) -> ShoppingList:
    """The list for a MealPlan's committed meals as of `now`; `prices` is prices.price_table()."""
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
        line = Line(name, need.net, need.demand, need.eligible, need.target, d["first"], d["recipes"], d["optional"], each)
        if line.buy > 0:
            price = food_price(client, prices, root) if prices is not None else None
            if price is not None and price.quantity.get("value") == 0:
                not_bought.append(name)                # a price of nothing: not something to shop for
                continue
            if price is not None and price.quantity.get("value") is not None:
                line.cost = line.buy * price.quantity["value"] / 100.0
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


def describe(shopping: ShoppingList, zone, level: str | None = None) -> str:
    """The list in words, grouped by the day each food is first needed (in `zone`)."""
    lines = [f"Shopping list for {shopping.week}: {shopping.cooks} meals to cook, {shopping.leftovers} of leftovers "
             f"(which need nothing more).",
             "What the meals call for, less what the pantry holds; amounts are what the recipes use, not package sizes."]
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
        lines.append(f"  {line.food:<{width}}  {line.amount():<24} {cost:>8}   {'; '.join(extra)}")
    if level:
        lines.append(f"\nAbout ${shopping.total:,.2f} at {level!r}" + (" (* priced from an estimate)" if any(
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
