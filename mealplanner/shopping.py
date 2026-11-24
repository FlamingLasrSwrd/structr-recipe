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

What is bought is the form a shop sells (mealplanner/yields.py, data-model.md J41, stage 3 of
docs/todo.md's "What ingredients are sold in"). A food another food yields (lemon juice, egg whites),
and that the package level sells in no size of its own, is bought as that food: what the pantry does
not cover of it, divided by the yield, joins that food's line, and stock of that food counts against
it. A food with a trim (an onion's skin) is bought by weight as it is sold: a package by weight or
volume holds that fraction of what a recipe weighs, and a need bought loose is divided by it, so the
grams a line buys, has left over and is priced by stay those a recipe weighs. A count of items is of
the edible part already. Leftover meals add nothing: they eat what an earlier cook made.

Known limits: one step of yield only (a food yielded by a food yielded by another is not followed);
a price is read per gram as a recipe weighs it, as Purchase to Plate's are, so an owner's price for a
trimmed food, stated per gram as bought, prices it a little low; and the pantry books what is bought
as it is weighed, so stock of a trimmed food bought by weight is counted with its trimmings.
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
from mealplanner.substitutes import entry_inputs
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from mealplanner.yields import edible_fraction, made_from
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
    made: list[tuple[str, float]] = field(default_factory=list)   # (food, grams of it): what this is bought to make
    edible: float = 1.0             # of a gram as bought, what a recipe weighs (its trim)
    trimmed: str = ""               # what the trim cuts away
    as_bought: float | None = None  # grams as bought: the packages' weight, the items', or the loose need over `edible`
    instead: list[str] = field(default_factory=list)   # the foods the recipes name, that this was bought in place of

    def amount(self) -> str:
        if self.packages:
            sizes = " + ".join(f"{n} x {label}" for n, label in self.packages)
            return f"{sizes} (about {self.as_bought if self.as_bought is not None else self.bought:,.0f} g)"
        grams = self.buy if self.buy > 0 else self.need
        if self.each:
            count = math.ceil(grams / self.each - 1e-9)
            return f"{count} (about {self.bought or grams:,.0f} g)"
        if self.as_bought is not None and self.edible < 1:
            return f"{_grams_text(self.as_bought)} as bought"
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
    or whole items for a food the recipes count, or as much as is needed. A food with a trim is
    bought as it is sold: a package by weight or volume holds `edible` of its weight as a recipe
    weighs it, and a loose need is bought over `edible`; a count of items is of the edible part.
    `bought` and `left` are in grams as a recipe weighs them, `as_bought` as the shop weighs them."""
    found = []
    for p in (food_packages(client, packages, root) if packages is not None else ()):
        grams = convert_to_grams(client, root, p.amount, p.unit)
        if grams:
            found.append((grams, p, UNIT_TABLE[p.unit][0] == "count"))
    if any(not counted for _, _, counted in found) or not (found or line.each):    # bought by weight
        line.edible, line.trimmed = edible_fraction(client, root)
    sizes = [(grams if counted else grams * line.edible, grams, p) for grams, p, counted in found]
    if sizes:
        counts = choose([held for held, _, _ in sizes], line.buy)
        line.packages = [(n, p.label) for n, (_, _, p) in zip(counts, sizes) if n]
        line.estimated_size = any(p.estimated for n, (_, _, p) in zip(counts, sizes) if n)
        line.bought = sum(n * held for n, (held, _, _) in zip(counts, sizes))
        line.as_bought = sum(n * grams for n, (_, grams, _) in zip(counts, sizes))
    elif line.each:
        line.bought = math.ceil(line.buy / line.each - 1e-9) * line.each
        line.as_bought = line.bought
    else:
        line.bought = line.buy
        line.as_bought = line.buy / line.edible
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
        inputs = [s for s in specs if s.get("hasParticipationRole") == "input" and s.get("specifies")
                  and s["specifies"]["id"] not in produced]
        for item in entry_inputs(client, entry, inputs):     # a food bought instead followed (substitutes.py)
            food, spec, grams = item.food, item.spec, item.grams
            if not grams:
                used_by = unquantified.setdefault(food.get("name") or food["id"], [])
                if plan["name"] not in used_by:
                    used_by.append(plan["name"])
                continue
            d = details.setdefault(_pool_root(client, food["id"]), {"recipes": [], "first": None, "optional": True,
                                                                   "counted": False})
            d["counted"] = d["counted"] or item.counted
            if item.original is not None:
                instead = d.setdefault("instead", [])
                if (item.original.get("name") or item.original["id"]) not in instead:
                    instead.append(item.original.get("name") or item.original["id"])
            if plan["name"] not in d["recipes"]:
                d["recipes"].append(plan["name"])
            if start is not None and (d["first"] is None or start < d["first"]):
                d["first"] = start
            d["optional"] = d["optional"] and bool(spec.get("isOptional"))
    # A food another yields, and that no package level sells in a size of its own, is bought as that
    # food (yields.made_from): its pool still counts its own stock first, and what that leaves joins
    # the other food's line, over the yield, where the other food's stock counts against it.
    bought_as = {}
    for root in details:
        if packages is not None and food_packages(client, packages, root):
            continue
        made = made_from(client, root)
        if made is not None:
            bought_as[root] = (made, _pool_root(client, made.source))
    sources = {src for _, src in bought_as.values()}
    bought_as = {root: v for root, v in bought_as.items() if root not in sources}     # one step: a source is bought as itself
    needs = acquisition(client, meal_plan_id, now, also=sorted({src for _, src in bought_as.values()}))
    extra: dict[str, float] = {}
    made_for: dict[str, list[tuple[str, float]]] = {}
    for root, (made, src) in bought_as.items():
        need = needs.get(root)
        if need is None or need.net < SHORT_G:
            continue                               # its own stock covers it: on the list as covered
        name = client.get_all("DomainType", root)["result"].get("name") or root
        extra[src] = extra.get(src, 0.0) + need.net / made.factor
        made_for.setdefault(src, []).append((name, need.net))
        d, s = details[root], details.setdefault(src, {"recipes": [], "first": None, "optional": True, "counted": False})
        s["recipes"] += [r for r in d["recipes"] if r not in s["recipes"]]
        if d["first"] is not None and (s["first"] is None or d["first"] < s["first"]):
            s["first"] = d["first"]
        s["optional"] = s["optional"] and d["optional"]
        s["counted"] = s["counted"] or bool(convert_to_grams(client, src, 1, "each"))   # lemons, eggs: whole items
    to_buy, covered, unpriced, not_bought = [], [], [], []
    for root, need in needs.items():
        if root in bought_as and need.net >= SHORT_G:
            continue                               # bought as another food: on that food's line
        demand = need.demand + extra.get(root, 0.0)
        net = max(0.0, demand + need.target - need.eligible)
        if demand <= 0 and net <= 0:
            continue                               # a policy's pool with nothing to do this week
        d = details.get(root, {"recipes": [], "first": None, "optional": False, "counted": False})
        name = client.get_all("DomainType", root)["result"].get("name") or root
        each = convert_to_grams(client, root, 1, "each") if d["counted"] else None
        buy = net if net >= SHORT_G else 0.0
        line = Line(name, buy, demand, need.eligible, need.target, d["first"], d["recipes"], d["optional"], each)
        line.made = made_for.get(root, [])
        line.instead = sorted(d.get("instead", []))
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
    made_names = {food for line in to_buy for food, _ in line.made}
    for food in list(unquantified):
        if any(line.food == food for line in to_buy + covered) or food in not_bought or food in made_names:
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
        if line.made:
            extra.append("for " + ", ".join(f"{food} ({grams:,.0f} g)" for food, grams in line.made))
        if line.instead:
            extra.append("bought in place of " + ", ".join(line.instead))
        if line.edible < 1 and not (line.each and not line.packages):
            extra.append(f"{line.edible:.0%} of it as bought is used" + (f" (less {line.trimmed})" if line.trimmed else ""))
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
        instead = lambda line: f", in place of {', '.join(line.instead)}" if line.instead else ""
        lines.append("\nThe pantry covers: " + ", ".join(f"{line.food} ({line.need:,.0f} of {line.have:,.0f} g{instead(line)})"
                                                          for line in shopping.covered))
    if shopping.unquantified:
        lines.append("\nNo amount in the recipe, so check there is some: " + ", ".join(
            f"{food} ({', '.join(recipes)})" for food, recipes in sorted(shopping.unquantified.items())))
    return "\n".join(lines)
