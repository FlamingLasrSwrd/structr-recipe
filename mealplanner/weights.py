"""A recipe's amounts shown as weights, for a person who prefers weighing (docs/todo.md, "Usable
measurements in recipes"; docs/recipe-format.md, "Amounts as weights").

Nothing is stored: a recipe keeps its source's measure, so its Plan version, nutrition and costs are
untouched. Each amount is converted as it is shown, by the food's own density or weight per item
(unit_conversion), and rounded to a step that suits the food:

  - the step is a tenth of one of the food's items ("each": an egg, 50 g, rounds to 5 g), or, for a
    food with no single item (flour, rice, oil), a tenth of its usual serving ("ServingSize": flour,
    30 g, rounds to 2 g after the snap below);
  - the step is then snapped to the nearest tidy step, 1, 2 or 5 times a power of ten, on a ratio
    scale, so an onion's 15 g step becomes 20 g;
  - a food with neither rounds to the gram.

The owner's decisions (2026-10-31 and 2026-11-23) say what stays as written: what is counted, like
eggs or garlic cloves; an amount stated by volume that weighs under 10 g, since "most kitchen scales
cannot accurately measure below about 10 grams"; an amount whose food has no density (never a
guess); and an amount that would round to nothing.

pages/lib/10_units.js has the same arithmetic (`tidyStep`, `roundingStep`, `shownAmount`) for the
recipe page and the instructions it writes; tools/check_instructions.py compares the two writers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mealplanner.unit_conversion import UNIT_TABLE

STEP_SHARE = 0.1                 # a tenth of an item, or of a serving (the owner, 2026-11-23)
SMALLEST_WEIGHED_G = 10.0        # a volume amount lighter than this stays as written (the owner, 2026-10-31)
# The tidy steps, 1, 2 and 5 times a power of ten. Written out, not computed with powers or logarithms,
# so that Python and JavaScript choose the same one to the last bit.
TIDY_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0)


@dataclass(frozen=True)
class FoodWeights:
    """What it takes to weigh a food: grams per mL, grams per item and grams in a usual serving, each
    None where the food has none."""
    density: float | None = None
    each: float | None = None
    serving: float | None = None


def tidy_step(x: float) -> float:
    """The tidy step nearest x on a ratio scale: between two neighbours a and b, x goes to a when
    x * x <= a * b (x at most their geometric mean), else on. Outside the ladder, its end."""
    for a, b in zip(TIDY_STEPS, TIDY_STEPS[1:]):
        if x * x <= a * b:
            return a
    return TIDY_STEPS[-1]


def rounding_step(food: FoodWeights | None) -> float | None:
    """The step a weight of this food is rounded to: a tenth of an item, else of a usual serving,
    snapped to a tidy step; None when the food has neither."""
    base = (food.each or food.serving) if food else None
    return tidy_step(base * STEP_SHARE) if base else None


def round_half_up(x: float) -> float:
    """Math.round's rounding (half up), so Python and JavaScript agree."""
    return math.floor(x + 0.5)


def to_grams(amount: float, unit: str | None, food: FoodWeights | None) -> float | None:
    """unit_conversion.convert_to_grams over facts already read: None for a count, an unknown unit,
    or a volume with no density."""
    entry = UNIT_TABLE.get(str(unit or "").strip().lower())
    if amount is None or entry is None:
        return None
    kind, factor = entry
    if kind == "mass":
        return amount * factor
    if kind == "volume" and food is not None and food.density:
        return amount * factor * food.density
    return None


def shown_amount(amount: float | None, unit: str | None, food: FoodWeights | None) -> tuple[float | None, str | None]:
    """(amount, unit) as a person who prefers weights is shown it: grams, rounded to the food's step,
    or the amount as written where it stays (see the module)."""
    entry = UNIT_TABLE.get(str(unit or "").strip().lower())
    if amount is None or entry is None or entry[0] == "count":
        return amount, unit
    grams = to_grams(amount, unit, food)
    if grams is None or (entry[0] == "volume" and grams < SMALLEST_WEIGHED_G):
        return amount, unit
    step = rounding_step(food) or 1.0
    rounded = round_half_up(round_half_up(grams / step) * step * 1e6) / 1e6     # 71 * 0.1 is 7.1000000000000005
    if rounded <= 0:
        return amount, unit
    return rounded, "g"


def serving_grams(value: float | None, unit: str | None, density: float | None) -> float | None:
    """A usual serving in grams: stated by weight, or by volume through the food's density."""
    if value is None:
        return None
    return to_grams(value, unit, FoodWeights(density=density))


def food_weights(client, food_type_id: str) -> FoodWeights:
    """A food's FoodWeights, read from the graph: its Density, MassPerUnit and ServingSize defaults,
    each resolved along its hierarchy (data-model.md Sec 8)."""
    from mealplanner.defaults import resolve_default

    def resolved(kind_name: str):
        kinds = client.get("/structr/rest/DomainType", params={"name": kind_name})["result"]
        if not kinds:
            return None
        found = resolve_default(client, food_type_id, kinds[0]["id"])
        return found.quantity if found else None

    density = resolved("Density")
    each = resolved("MassPerUnit")
    serving = resolved("ServingSize")
    d = density.get("value") if density and density.get("unit") == "g_per_mL" else None
    e = each.get("value") if each and each.get("unit") == "g_per_each" else None
    s = serving_grams(serving.get("value"), serving.get("unit"), d) if serving else None
    return FoodWeights(d, e, s)
