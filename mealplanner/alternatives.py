"""What could take the place of a food on the shopping list, best first, each with what it does to the
week's cost and nutrition (docs/todo.md, "Suggest alternatives on the shopping list").

"The grocery list has an item that is not available" (the owner, 2026-11-23). For a line of a committed
week's list, the meals still to cook that need its food (substitutes.meals_needing), and in this order:

  same     the food itself in another size or brand, or a kind of it: stock of the food, so it counts for
           every meal with no swap, and the week's nutrition and cost per gram do not change
  recipe   what the recipes themselves say may stand in (J36), with their ratios, for the meals whose recipe
           says so: checked against the recipe
  similar  foods beside it in the Food Identity hierarchy, one to one by weight, NOT checked against any
           recipe: a suggestion only. Foods a recipe rules out are left out. Ranked by those with a price and
           a nutrient profile first, then by how close their energy per 100 g is, then by name
  replan   none of these: the meals planned again without it (skipped on the week page, and the planner run
           on the free meals, tools/plan_week.py)

Within `recipe`, food already on hand comes first, then one that covers every meal, then the cheaper.
What each does is worked out over the meals it covers, as the meals are planned (servings planned over
the recipe's yield): the cost at a price level per gram as the recipes weigh it, before rounding to
packages (what is bought in packages is the shopping list's, once the swap is booked), and the change in
each nutrient a target is about, in the dishes as cooked (substitutes._contribution: grams x per 100 g x
the step's retention factor), or None where a figure is missing. Choosing one books the purchase and the
swap (substitutes.buy_instead). pages/lib/92_substitutes.js does the same for the shopping page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.inventory import eligible_lots
from mealplanner.material_accounting import recipe_servings_strict
from mealplanner.nutrition_scope import profile_figure, raw_inputs
from mealplanner.prices import food_price
from mealplanner.substitutes import Swap, _contribution, meals_needing, swapped_grams
from mealplanner.typetree import dt, subtypes_of
from mealplanner.unit_conversion import convert_to_grams
from structr_client import ReadCache

MAX_SIMILAR = 6                 # similar foods shown
MAX_CONSIDERED = 40             # similar foods looked at, nearest in the hierarchy first
ENERGY = "Energy"               # the nutrient similar foods are ranked by closeness of, per 100 g, in kcal
COUNT_UNITS = ("each", "whole", "count")


@dataclass
class Effect:
    cost: float | None                                      # dollars more (+) or less (-), None if a price is missing
    nutrients: list[tuple[str, str, float | None]] = field(default_factory=list)   # (nutrient, unit, change)


@dataclass
class Alternative:
    kind: str                       # "same", "recipe", "similar" or "replan"
    food: str | None                # what is bought instead (None for same and replan)
    meals: list[str]                # the meals (entry names) it is for
    grams: float = 0.0              # of it, what those meals take
    have: float = 0.0               # of it, eligible stock on hand
    ratio: float | None = None      # a recipe rule's, for one of the original in the recipe's unit
    effect: Effect | None = None
    kinds: list[str] = field(default_factory=list)          # same: the food's own kinds and products

    @property
    def checked(self) -> bool:
        return self.kind != "similar"


@dataclass
class Alternatives:
    food: str
    grams: float                                            # what the meals take of it
    meals: list[tuple[str, str]]                            # (entry name, recipe name)
    options: list[Alternative]


@dataclass
class _Use:
    entry: dict
    spec: dict
    step: dict | None               # the step taking it, where it is a raw input nutrition counts
    scale: float                    # servings planned over the recipe's yield
    grams: float | None             # of the original, scaled


def _uses(client, meal_plan_id: str, food_id: str) -> list[_Use]:
    out = []
    for entry, specs in meals_needing(client, meal_plan_id, food_id):
        plan = client.get_all("Plan", entry["references"]["id"])["result"]
        servings = recipe_servings_strict(client, plan)
        if not servings:
            continue
        scale = entry["hasPlannedServings"] / servings
        steps = {spec["id"]: step for step, spec in raw_inputs(client, plan)}
        for spec in specs:
            qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"] \
                if spec.get("hasSpecifiedQuantity") else {}
            grams = convert_to_grams(client, spec["specifies"]["id"], qty["value"], qty.get("unit")) \
                if qty.get("value") is not None else None
            out.append(_Use(entry, spec, steps.get(spec["id"]), scale, grams * scale if grams else None))
    return out


def _quantity(client, spec: dict) -> dict:
    return client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"] \
        if spec.get("hasSpecifiedQuantity") else {}


def effect(client, uses: list[_Use], swap_of, prices: dict | None, nutrients: dict) -> tuple[Effect, float]:
    """(what standing in does over these uses, the grams of what stands in): `swap_of(use)` is the Swap for a
    use. The cost per gram as the recipes weigh it; each nutrient over the raw inputs nutrition counts."""
    cost: float | None = 0.0
    taken = 0.0
    changes = {nid: 0.0 for nid in nutrients}
    for use in uses:
        swap = swap_of(use)
        qty = _quantity(client, use.spec)
        grams = swapped_grams(client, use.spec["specifies"]["id"], qty, swap)
        grams = grams * use.scale if grams else None
        taken += grams or 0.0
        if cost is not None:
            before = food_price(client, prices, use.spec["specifies"]["id"]) if prices is not None else None
            after = food_price(client, prices, swap.food) if prices is not None else None
            values = [p.quantity.get("value") if p is not None else None for p in (before, after)]
            if None in values or grams is None or use.grams is None:
                cost = None
            else:
                cost += (grams * values[1] - use.grams * values[0]) / 100.0
        if use.step is None:
            continue                    # optional, or made by the recipe: no share in its nutrition
        method = (use.step.get("instanceOf") or {}).get("id")
        value, unit = qty.get("value"), str(qty.get("unit") or "").strip().lower()
        counted = unit in COUNT_UNITS and value is not None
        for nid, (_, nunit) in nutrients.items():
            if changes[nid] is None:
                continue
            original = use.spec["specifies"]["id"]
            was = _contribution(client, original, use.spec, use.grams / use.scale if use.grams else None,
                                value if counted else None, method, nid, nunit)[0]
            now = _contribution(client, swap.food, use.spec, grams / use.scale if grams else None,
                                value * swap.ratio if counted and not swap.one_off else None, method, nid, nunit)[0]
            changes[nid] = None if was is None or now is None else changes[nid] + (now - was) * use.scale
    names = sorted(nutrients.items(), key=lambda kv: kv[1][0])
    return Effect(cost, [(name, unit, changes[nid]) for nid, (name, unit) in names]), taken


def _have(client, food_id: str, now: datetime) -> float:
    return sum(lot.grams for lot in eligible_lots(client, food_id, now))


def _energy(client, food_id: str) -> float | None:
    ids = [r["id"] for r in client.get("/structr/rest/DomainType", params={"name": ENERGY})["result"]]
    if len(ids) != 1:
        return None
    figure = profile_figure(client, food_id, ids[0])
    if figure is None:
        return None
    from mealplanner.nutrition_scope import convert_nutrient
    return convert_nutrient(figure.amount, figure.unit, "kcal")


def neighbours(client, food_id: str, leave_out: set[str], products: set[str]) -> list[str]:
    """Foods beside one in its hierarchy, nearest first: below its parent, then its grandparent, down to two
    levels below each, and none of `leave_out` or the products (which have no figures of their own); at most
    MAX_CONSIDERED, by name within each distance."""
    node = client.get_all("DomainType", food_id)["result"]
    found: list[str] = []
    seen = set(leave_out) | subtypes_of(client, food_id)
    above = node.get("parent")
    for depth in (2, 3):
        if not above or len(found) >= MAX_SIMILAR:
            break
        level, frontier = [], [above["id"]]
        for _ in range(depth):
            nxt = []
            for tid in frontier:
                for child in client.get_all("DomainType", tid)["result"].get("children", []):
                    if child["id"] in seen:
                        continue
                    seen.add(child["id"])
                    nxt.append(child["id"])
                    if child["id"] not in products:
                        level.append((child.get("name") or child["id"], child["id"]))
            frontier = nxt
        found += [tid for _, tid in sorted(level)]
        above = client.get_all("DomainType", above["id"])["result"].get("parent")
    return found[:MAX_CONSIDERED]


def alternatives(client, meal_plan_id: str, food: str, now: datetime, prices: dict | None = None,
                 nutrients: dict | None = None) -> Alternatives:
    """What could stand in for `food` (a shopping line's food, by name) in a week's meals still to cook;
    `prices` is prices.price_table(), `nutrients` {nutrient id: (name, unit)} (recipe_nutrition.targeted_nutrients)."""
    from mealplanner.products import product_ids
    from mealplanner.recipe_nutrition import targeted_nutrients
    client = ReadCache(client)
    nutrients = targeted_nutrients(client) if nutrients is None else nutrients
    food_id = dt(client, food)
    uses = _uses(client, meal_plan_id, food_id)
    meals, seen = [], set()
    for use in uses:
        if use.entry["id"] not in seen:
            seen.add(use.entry["id"])
            meals.append((use.entry.get("name"), (use.entry.get("references") or {}).get("name")))
    entry_names = [m for m, _ in meals]
    options: list[Alternative] = []
    products = product_ids(client)

    # same: the food in another size or brand, or a kind of it
    kinds = sorted((client.get_all("DomainType", t)["result"].get("name") or t) for t in subtypes_of(client, food_id) - {food_id})
    options.append(Alternative("same", None, entry_names, sum(u.grams or 0.0 for u in uses), _have(client, food_id, now),
                               effect=Effect(0.0, [(n, u, 0.0) for _, (n, u) in sorted(nutrients.items(), key=lambda kv: kv[1][0])]),
                               kinds=kinds))

    # recipe: the recipes' own rules, grouped by what stands in
    ruled_out: set[str] = set()
    by_food: dict[str, list] = {}
    for use in uses:
        for ref in use.spec.get("hasSubstitutionRule") or []:
            rule = client.get_all("SubstitutionRule", ref["id"])["result"]
            cand = rule.get("candidateType")
            if not cand or rule.get("isOneOff"):
                continue
            if rule.get("isExcluded"):
                ruled_out.add(cand["id"])
                continue
            ratio = rule.get("substitutionRatio")
            by_food.setdefault(cand["id"], []).append((use, Swap(rule["id"], cand["id"], cand.get("name") or cand["id"],
                                                                 1.0 if ratio is None else float(ratio), False)))
    recipe_options = []
    for cand_id, pairs in by_food.items():
        swaps = {id(use): swap for use, swap in pairs}
        covered = [use for use, _ in pairs]
        eff, grams = effect(client, covered, lambda u: swaps[id(u)], prices, nutrients)
        names = []
        for use in covered:
            if use.entry.get("name") not in names:
                names.append(use.entry.get("name"))
        ratios = {swap.ratio for _, swap in pairs}
        recipe_options.append(Alternative("recipe", pairs[0][1].food_name, names, grams, _have(client, cand_id, now),
                                          ratios.pop() if len(ratios) == 1 else None, eff))
    recipe_options.sort(key=lambda a: (a.have <= 0, len(a.meals) < len(entry_names),
                                       a.effect.cost is None, a.effect.cost or 0.0, a.food))
    options += recipe_options

    # similar: foods beside it, one to one by weight, not checked against a recipe
    listed = set(by_food) | ruled_out
    target = _energy(client, food_id)
    ranked = []
    for cand_id in neighbours(client, food_id, listed, products):
        name = client.get_all("DomainType", cand_id)["result"].get("name") or cand_id
        swap = Swap("", cand_id, name, 1.0, True)
        energy = _energy(client, cand_id)
        priced = prices is not None and food_price(client, prices, cand_id) is not None
        ranked.append(((energy is None) + (not priced), abs(energy - target) if energy is not None and target is not None
                       else float("inf"), name, cand_id, swap))
    ranked.sort(key=lambda r: r[:3])
    for _, _, name, cand_id, swap in ranked[:MAX_SIMILAR]:
        eff, grams = effect(client, uses, lambda u, s=swap: s, prices, nutrients)
        options.append(Alternative("similar", name, entry_names, grams, _have(client, cand_id, now), 1.0, eff))

    options.append(Alternative("replan", None, entry_names))
    return Alternatives(food, sum(u.grams or 0.0 for u in uses), meals, options)


def describe(alts: Alternatives, level: str | None = None) -> str:
    """The alternatives in words, as the shopping page lists them."""
    lines = [f"In place of {alts.food} ({alts.grams:,.0f} g for {', '.join(m for m, _ in alts.meals) or 'no meal still to cook'}):"]
    for a in alts.options:
        if a.kind == "same":
            text = "the same food, any size or brand" + (f", or a kind of it: {', '.join(a.kinds)}" if a.kinds else "")
            text += "; it counts for every meal, and nothing changes"
        elif a.kind == "replan":
            text = "plan the meals again without it (skip them on the week page, then run tools/plan_week.py)"
        else:
            how = ("the recipe's own rule" + (f", {a.ratio:g} for 1" if a.ratio not in (None, 1.0) else "")) if a.kind == "recipe" \
                else "one to one by weight; not checked against the recipe"
            cost = "" if a.effect.cost is None else f"; {'+' if a.effect.cost >= 0 else '-'}${abs(a.effect.cost):,.2f}"
            text = f"{a.food} ({how}): {a.grams:,.0f} g for {', '.join(a.meals)}" + (f"; have {a.have:,.0f} g" if a.have > 0 else "") + cost
            changed = [f"{n} {'+' if c >= 0 else ''}{c:,.1f} {u}" for n, u, c in a.effect.nutrients if c is not None and abs(c) >= 0.05]
            unknown = [n for n, _, c in a.effect.nutrients if c is None]
            if changed:
                text += "; " + ", ".join(changed)
            if unknown:
                text += "; not known: " + ", ".join(unknown)
        lines.append(f"  {a.kind:<8} {text}")
    if level:
        lines.append(f"Costs at {level!r}, per gram before packages.")
    return "\n".join(lines)
