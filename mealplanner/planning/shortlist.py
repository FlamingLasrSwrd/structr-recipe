"""A weekly shortlist: the recipes a large book's week is read and searched over (the owner's
decision, 2026-10-22; docs/optimizer-design.md Sec 12).

Measured on the owner's household week with its 40 recipes cloned: the whole book found a
week meeting every hard target in 27 s at 40 recipes, none in 30 s at 120 or 200, and at
1,000 its model would need several GB. The search grows with every recipe it weighs, so
a book larger than SHORTLIST_ABOVE is cut, before its recipes are read in full, to the ones
most worth weighing; a week then took about 30 s whatever the book's size (36 s and 371 MB
at 1,000).

The ranking (scores) is a recipe's fit to the week's people, from its stored figures per
serving: for every daily target of every eater, how close its nutrient per calorie comes
to what the target asks per calorie, after that eater's baseline; plus the time fit, less
any soft exclusion. Per calorie, because the energy targets cap the calories: a large
serving rich in fibre can still be a poor way to meet a fibre target. An unknown figure
counts as neutral, as the objective scores it.

The choice (choose): for each meal type of the week's open slots, the best-ranked recipes
tagged for it, FACTOR times as many as it has slots; and for each hard minimum, the
COVERAGE recipes richest in it, so that a minimum the best-ranked could not reach stays
reachable. One version per recipe (the best-ranked), so the shortlist is not spent on
near-copies. A ranking only orders the search: the week found is scored by the objective
as before, and it is not proven best over the whole book.

When the shortlist holds no week meeting every hard target, planning/plan.py doubles FACTOR
and reads and searches again, until the shortlist is the whole book (a growing core, after
Balas and Zemel's for large knapsack problems).
"""

from __future__ import annotations

import math
from mealplanner.planning.evaluate import ineligible_reason
from mealplanner.planning.model import PlanningProblem
from mealplanner.scoring import NEUTRAL, time_fit_score

SHORTLIST_ABOVE = 60       # a larger book is shortlisted; measured: 40 searched whole in 27 s, 120 found nothing in 30 s
FACTOR = 2.0               # recipes per open slot of a meal type
COVERAGE = 2               # recipes richest in each hard minimum, per meal type
HARD_WEIGHT = 1.0          # a hard target weighs in the ranking as a soft one of weight 1 would
ENERGY_UNITS = ("kcal", "kj")


def _energy(problem: PlanningProblem) -> str | None:
    return next((n for n, u in sorted(problem.units.items()) if (u or "").lower() in ENERGY_UNITS), None)


def _day_energy(problem: PlanningProblem, eater: str, energy: str | None) -> float | None:
    """The middle of an eater's daily energy range (or the one bound it has); None without one."""
    for t in problem.targets:
        if t.eater == eater and t.nutrient == energy and t.scope == "daily":
            if t.minimum is not None and t.maximum is not None:
                return (t.minimum + t.maximum) / 2
            return t.minimum if t.minimum is not None else t.maximum
    return None


def _fit(density: float, lo: float | None, hi: float | None) -> float:
    """1 within [lo, hi] per calorie; below lo, the share of it reached; above hi, falling to 0 at twice it."""
    if lo is not None and density < lo:
        return density / lo
    if hi is not None and density > hi:
        return max(0.0, 2.0 - density / hi) if hi > 0 else 0.0
    return 1.0


def scores(problem: PlanningProblem) -> dict[str, float]:
    """Each candidate's fit to the week's people (see the module)."""
    energy = _energy(problem)
    w = problem.weights
    out = {}
    for c in problem.candidates.values():
        score = w.time * time_fit_score(c.minutes, w.time_budget_minutes) - c.soft_penalty
        score -= w.cooking_time * (c.minutes if c.minutes is not None else w.time_budget_minutes) / 60.0
        kcal = c.nutrients.get(energy) if energy else None
        for t in problem.targets:
            weight = HARD_WEIGHT if t.hard else t.weight
            if t.scope != "daily" or t.nutrient == energy or weight <= 0:
                continue
            day_kcal = _day_energy(problem, t.eater, energy)
            amount = c.nutrients.get(t.nutrient)
            if amount is None or not kcal or not day_kcal:
                score += weight * NEUTRAL
                continue
            base = problem.baseline_of(t.eater).get(t.nutrient) or 0.0
            lo = None if t.minimum is None or t.minimum <= base else (t.minimum - base) / day_kcal
            hi = None if t.maximum is None else max(0.0, t.maximum - base) / day_kcal
            score += weight * _fit(amount / kcal, lo, hi)
        out[c.id] = score
    return out


def choose(problem: PlanningProblem, factor: float = FACTOR, coverage: int = COVERAGE) -> set[str]:
    """The shortlist's candidate ids (see the module). `problem` holds the week's open slots."""
    ranked = scores(problem)
    order, seen = [], set()
    for c in sorted(problem.candidates.values(), key=lambda c: (-ranked[c.id], c.name, c.id)):
        recipe = c.recipe or c.id
        if recipe not in seen:                     # one version per recipe: its best-ranked
            seen.add(recipe)
            order.append(c)
    slots_of: dict = {}                            # the open slots of each meal type
    for i in problem.open_slots():
        slots_of.setdefault(problem.slots[i].meal_type, []).append(i)
    chosen: set[str] = set()
    for meal_type, slots in slots_of.items():
        # fit for at least one of them: a dish made ahead may be too late for the first
        fits = [c for c in order if any(ineligible_reason(problem, i, c) is None for i in slots)]
        chosen |= {c.id for c in fits[:math.ceil(len(slots) * factor)]}
        for t in problem.targets:
            if t.hard and t.minimum is not None:
                richest = sorted(fits, key=lambda c: (-(c.nutrients.get(t.nutrient) or 0.0), c.name, c.id))
                chosen |= {c.id for c in richest[:coverage]}
    return chosen
