"""A food bought in place of what the shopping list says, and the meals of the week that then use it
(docs/todo.md, "A substitute bought in place of what the list says"; data-model.md J42).

"If the grocery list says blue corn tortilla chips but the store is out, substitute whatever the user
buys in the recipes" (the owner, 2026-11-23). The recipe is left as it is. What changes is the week:
each meal that was to use the listed food now uses the bought one, for that meal only, through a
SubstitutionRule on the recipe's own input (J36):

  MealPlanEntry -[USES_SUBSTITUTION]-> SubstitutionRule      usesSubstitution / usedByEntries
      the rules a planned meal uses: for that meal, the rule's input is the rule's candidate
  SubstitutionRule.isOneOff (Boolean)
      a rule made for the meals that use it, not one of the recipe's own: the recipe's sentences leave it
      out, a recipe loaded again keeps it, and its ratio is by weight (one to one unless it says otherwise)
  Allocation -[VIA_SUBSTITUTION]-> SubstitutionRule          viaSubstitution / allocationsVia
      the model's via_substitution (data-model.md Sec 5, invariant 18): a cook's draw says which rule it
      followed, so what was really used can be told from what the recipe says

Where the recipe has a rule of its own for the bought food (yellow corn chips for blue, "or 1 cup of
yellow"), the meal uses that rule and its ratio, which is in the recipe's own unit. Otherwise a one-off
rule is made then, one to one by weight. A recipe's rule that rules the food out (isExcluded) is kept to:
that meal is left as it is.

Everything that reads what a meal takes follows a swap: the shopping list and the reservations
(reservation.committed_requirements), a cook's draws (pantry.cook), and a meal's nutrition
(nutrition_scope.entry_nutrient_figure, by swap_delta below). A meal using no rule is read exactly as
before, with no read more. pages/lib/92_substitutes.js does the same for the pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mealplanner.typetree import subtypes_of
from mealplanner.unit_conversion import convert_to_grams

SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}


@dataclass(frozen=True)
class Swap:
    rule: str             # the SubstitutionRule's id
    food: str             # what stands in: the rule's candidateType's id
    food_name: str
    ratio: float          # how much of it for one of the original: in the original's unit, or by weight (one_off)
    one_off: bool


def entry_swaps(client, entry: dict) -> dict[str, Swap]:
    """{input Specification id: the Swap a planned meal uses for it}. A rule that rules its food out, or
    names no input or no food, is not a swap; of two for one input, the first by name."""
    out: dict[str, Swap] = {}
    for ref in sorted(entry.get("usesSubstitution") or [], key=lambda r: (r.get("name") or "", r["id"])):
        rule = client.get_all("SubstitutionRule", ref["id"])["result"]
        spec, food = rule.get("forSpecification"), rule.get("candidateType")
        if not spec or not food or rule.get("isExcluded") or spec["id"] in out:
            continue
        ratio = rule.get("substitutionRatio")
        out[spec["id"]] = Swap(rule["id"], food["id"], food.get("name") or food["id"],
                               1.0 if ratio is None else float(ratio), bool(rule.get("isOneOff")))
    return out


def swapped_grams(client, original_id: str, quantity: dict, swap: Swap) -> float | None:
    """Grams of what stands in for an input's quantity (as the recipe states it, unscaled). A recipe's own
    rule is in the recipe's unit (0.75 tbsp of oil for a tbsp of butter), converted for the food that
    stands in; where that food has no conversion for the unit, and for a one-off rule, by weight."""
    value, unit = quantity.get("value"), quantity.get("unit")
    if value is None:
        return None
    if not swap.one_off:
        grams = convert_to_grams(client, swap.food, value * swap.ratio, unit)
        if grams:
            return grams
    original = convert_to_grams(client, original_id, value, unit)
    return original * swap.ratio if original else None


@dataclass
class Input:
    """What a planned meal takes for one input of its recipe, a swap followed."""
    spec: dict
    food: dict                      # {"id", "name"}: what is taken
    grams: float | None             # for the recipe as written (unscaled); None when no amount converts
    counted: bool                   # the amount is a count of items
    original: dict | None = None    # the food the recipe names, when a swap stands in for it
    swap: Swap | None = None


def entry_inputs(client, entry: dict, specs: list[dict]) -> list[Input]:
    """What a planned meal takes for each of its recipe's input Specifications in `specs` (fully loaded,
    in order), following the rules it uses."""
    swaps = entry_swaps(client, entry) if entry.get("usesSubstitution") else {}
    out = []
    for spec in specs:
        food = spec.get("specifies")
        if not food:
            continue
        qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"] \
            if spec.get("hasSpecifiedQuantity") else {}
        unit = str(qty.get("unit") or "").strip().lower()
        counted = unit in ("each", "whole", "count")
        swap = swaps.get(spec["id"])
        if swap is None:
            grams = convert_to_grams(client, food["id"], qty["value"], qty.get("unit")) if qty.get("value") is not None else None
            out.append(Input(spec, food, grams or None, counted))
        else:
            out.append(Input(spec, {"id": swap.food, "name": swap.food_name}, swapped_grams(client, food["id"], qty, swap),
                             counted and not swap.one_off, food, swap))
    return out


def entry_input_requirements(client, entry: dict, plan: dict) -> list[tuple[str, float]]:
    """material_accounting.candidate_input_requirements for one planned meal: [(food id, grams for the
    recipe as written)] for each raw input with an amount, a swap followed."""
    from mealplanner.material_accounting import candidate_input_requirements, plan_specifications
    if not entry.get("usesSubstitution"):
        return candidate_input_requirements(client, plan)
    specs = plan_specifications(client, plan)
    produced = {s["specifies"]["id"] for s in specs if s.get("hasParticipationRole") == "output" and s.get("specifies")}
    raw = [s for s in specs if s.get("hasParticipationRole") == "input" and s.get("specifies")
           and s.get("hasSpecifiedQuantity") and s["specifies"]["id"] not in produced]
    return [(i.food["id"], i.grams) for i in entry_inputs(client, entry, raw) if i.grams]


def source_entry(client, entry: dict, hops: int = 20) -> dict | None:
    """The planned meal whose cook an entry eats: itself, or for leftovers the cook they come from."""
    seen, current = set(), entry
    for _ in range(hops + 1):
        if current.get("references"):
            return current
        source = current.get("consumesLeftoverFrom")
        if not source or source["id"] in seen:
            return None
        seen.add(source["id"])
        current = client.get_all("MealPlanEntry", source["id"])["result"]
    return None


def _contribution(client, food_id: str, spec: dict, grams: float | None, count: float | None, method_id: str | None,
                  nutrient_id: str, unit: str) -> tuple[float | None, str | None, bool]:
    """(the nutrient an input brings to the dish, in `unit`, or None if unknown; its profile's provenance;
    whether no retention factor adjusted it): nutrition_scope._from_ingredients for one ingredient."""
    from mealplanner.nutrition_scope import convert_nutrient, profile_figure, retention_factor
    figure, per_unit = profile_figure(client, food_id, nutrient_id), False
    if figure is None:
        figure, per_unit = profile_figure(client, food_id, nutrient_id, basis="per_unit"), True
    if figure is None:
        return None, None, False
    per_basis = convert_nutrient(figure.amount, figure.unit, unit)
    if per_basis is None:
        return None, figure.provenance, False
    if per_basis == 0:
        return 0.0, figure.provenance, False
    if per_unit:
        if count is None:
            return None, figure.provenance, False
        amount = count * per_basis
    else:
        if grams is None:
            return None, figure.provenance, False
        amount = grams * per_basis / 100.0
    factor = retention_factor(client, food_id, method_id, nutrient_id)
    return amount * (1.0 if factor is None else factor), figure.provenance, factor is None


def swap_delta(client, entry: dict, plan: dict, nutrient_id: str, unit: str, servings: float) -> tuple[float | None, bool]:
    """(what a planned meal's swaps change in ONE serving of its recipe, in `unit`, or None if it cannot be
    told; whether the change rests on an estimate). For each raw input a swap stands in for: what the food
    taken brings, less what the recipe's food would have, each as nutrition_scope._from_ingredients counts
    it (grams x per 100 g x the step's retention factor, or a count x a per-unit label). An optional input
    counts for nothing either way, as it does in the recipe's figure."""
    from mealplanner.nutrition_scope import USABLE, raw_inputs
    swaps = entry_swaps(client, entry)
    if not swaps:
        return 0.0, False
    total, estimated = 0.0, False
    for step, spec in raw_inputs(client, plan):
        swap = swaps.get(spec["id"])
        if swap is None:
            continue
        method_id = (step.get("instanceOf") or {}).get("id")
        qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"] \
            if spec.get("hasSpecifiedQuantity") else {}
        value, qunit = qty.get("value"), str(qty.get("unit") or "").strip().lower()
        counted = qunit in ("each", "whole", "count")
        original = spec["specifies"]["id"]
        before = _contribution(client, original, spec,
                               convert_to_grams(client, original, value, qty.get("unit")) if value is not None else None,
                               value if counted else None, method_id, nutrient_id, unit)
        after = _contribution(client, swap.food, spec, swapped_grams(client, original, qty, swap),
                              value * swap.ratio if counted and value is not None and not swap.one_off else None,
                              method_id, nutrient_id, unit)
        if before[0] is None or after[0] is None:
            return None, False
        if after[1] not in USABLE or before[1] not in USABLE:
            return None, False
        total += after[0] - before[0]
        estimated = estimated or after[1] != "sourced" or after[2] or swap.one_off
    return total / servings, estimated


# --- booking a food bought instead -----------------------------------------------------------------

class SwapError(ValueError):
    pass


@dataclass
class Swapped:
    """What a swap booking did: per meal, a note; the names of the nodes it created."""
    created: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    meals: list[str] = field(default_factory=list)       # the entries now using the bought food


def meals_needing(client, meal_plan_id: str, food_id: str) -> list[tuple[dict, list[dict]]]:
    """[(entry, [input Specifications])]: the week's planned cooks, not cooked or skipped, whose recipe takes
    `food_id` or a food below it as an input it does not make, for an input no swap already stands in for."""
    from mealplanner.material_accounting import plan_specifications
    pool = subtypes_of(client, food_id)
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    out = []
    for ref in meal_plan.get("hasEntry", []):
        entry = client.get_all("MealPlanEntry", ref["id"])["result"]
        if entry.get("isSkipped") or entry.get("fulfilledBy") or not entry.get("references") \
                or entry.get("hasPlannedServings") is None:
            continue
        plan = client.get_all("Plan", entry["references"]["id"])["result"]
        specs = plan_specifications(client, plan)
        produced = {s["specifies"]["id"] for s in specs if s.get("hasParticipationRole") == "output" and s.get("specifies")}
        swapped = entry_swaps(client, entry) if entry.get("usesSubstitution") else {}
        mine = [s for s in specs if s.get("hasParticipationRole") == "input" and s.get("specifies")
                and s["specifies"]["id"] in pool and s["specifies"]["id"] not in produced and s["id"] not in swapped]
        if mine:
            out.append((entry, mine))
    return out


def recipe_rule(client, spec: dict, bought_id: str) -> dict | None:
    """The recipe's own rule on an input for the bought food: its candidate is the food or a food above it.
    One that rules it out is returned too (isExcluded), so that it is kept to."""
    from mealplanner.typetree import ancestors_or_self
    above = ancestors_or_self(client, bought_id)
    best = None
    for ref in spec.get("hasSubstitutionRule") or []:
        rule = client.get_all("SubstitutionRule", ref["id"])["result"]
        food = rule.get("candidateType")
        if rule.get("isOneOff") or not food or food["id"] not in above:
            continue
        rank = above.index(food["id"])
        if best is None or rank < best[0]:
            best = (rank, rule)
    return best[1] if best else None


def one_off_name(spec: dict, bought_name: str) -> str:
    return f"{spec.get('name') or spec['id']} or {bought_name} (bought instead)"


def use_instead(client, meal_plan_id: str, listed: str, bought: str, entry_ids=None) -> Swapped:
    """Have the week's meals that need `listed` (a food's name: a shopping line) use `bought` instead, each
    by the recipe's own rule for it where there is one, else by a one-off rule, one to one by weight. Only the
    meals in `entry_ids` when it is given. Found by name before anything is written, so booking it twice
    writes nothing new (hard rule 5). The purchase itself is pantry.buy's (buy_instead)."""
    from mealplanner.typetree import dt
    listed_id, bought_id = dt(client, listed), dt(client, bought)
    if bought_id in subtypes_of(client, listed_id):
        raise SwapError(f"{bought} is {listed} already: a product or kind of it stands in for it with no swap")
    from mealplanner.products import product_ids
    if bought_id in product_ids(client):          # a product has no figures of its own: the meals use its food
        parent = client.get_all("DomainType", bought_id)["result"].get("parent")
        if parent:
            bought_id, bought = parent["id"], parent.get("name") or parent["id"]
    done = Swapped()
    wanted = set(entry_ids) if entry_ids else None
    for entry, specs in meals_needing(client, meal_plan_id, listed_id):
        if wanted is not None and entry["id"] not in wanted:
            continue
        uses = [r["id"] for r in entry.get("usesSubstitution") or []]
        added = []
        for spec in specs:
            rule = recipe_rule(client, spec, bought_id)
            if rule is not None and rule.get("isExcluded"):
                done.notes.append(f"{entry.get('name')}: the recipe says {bought} must not stand in for "
                                  f"{spec['specifies'].get('name')}, so it is left as it is")
                continue
            if rule is None:
                name = one_off_name(spec, bought)
                found = [r for r in client.get("/structr/rest/SubstitutionRule", params={"name": name})["result"]
                         if r.get("type") == "SubstitutionRule"]
                if found:
                    rule_id = found[0]["id"]
                else:
                    rule_id = client.post("/structr/rest/SubstitutionRule", {
                        "name": name, "forSpecification": spec["id"], "candidateType": bought_id, "substitutionRatio": 1.0,
                        "isOneOff": True, "isExcluded": False, **SEEN})["result"][0]
                    done.created.append(name)
                how = "one to one by weight"
            else:
                rule_id = rule["id"]
                ratio = rule.get("substitutionRatio")
                how = "by the recipe's own rule" + ("" if ratio in (None, 1, 1.0) else f", {ratio:g} for 1")
            if rule_id not in uses and rule_id not in added:
                added.append(rule_id)
                done.notes.append(f"{entry.get('name')}: {bought} for {spec['specifies'].get('name')}, {how}")
        if added:
            client.patch(f"/structr/rest/MealPlanEntry/{entry['id']}", {"usesSubstitution": uses + added})
            done.meals.append(entry.get("name"))
    if not done.meals and not done.notes:
        done.notes.append(f"no meal of the week still to cook needs {listed}")
    return done


def buy_instead(client, meal_plan_id: str, listed: str, bought: str, amount: float, unit: str, when, token: str, *,
                storage: str = "Fridge", by: str | None = None, entry_ids=None):
    """Book a purchase of `bought` in place of `listed` (pantry.buy), and the week's meals that need `listed`
    use it (use_instead). Returns (the purchase's Booking, Swapped)."""
    from mealplanner.pantry import buy
    swapped = use_instead(client, meal_plan_id, listed, bought, entry_ids)
    booking = buy(client, bought, amount, unit, when, token, storage=storage, by=by)
    return booking, swapped


def stop_using(client, entry_id: str, rule_id: str) -> list[str]:
    """Undo a swap for one meal: it no longer uses the rule, and a one-off rule no meal uses any more is
    deleted. Not for a meal already cooked: its draws followed the rule. The purchase stays."""
    entry = client.get_all("MealPlanEntry", entry_id)["result"]
    if entry.get("fulfilledBy"):
        raise SwapError(f"{entry.get('name')}: cooked already, with the swap")
    uses = [r["id"] for r in entry.get("usesSubstitution") or []]
    if rule_id not in uses:
        return []
    client.patch(f"/structr/rest/MealPlanEntry/{entry_id}", {"usesSubstitution": [r for r in uses if r != rule_id]})
    rule = client.get_all("SubstitutionRule", rule_id)["result"]
    deleted = []
    if rule.get("isOneOff") and not [r for r in rule.get("usedByEntries") or [] if r["id"] != entry_id] \
            and not rule.get("allocationsVia"):
        client.delete(f"/structr/rest/SubstitutionRule/{rule_id}")
        deleted.append(rule.get("name"))
    return deleted
