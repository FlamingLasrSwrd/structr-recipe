"""Which nutrients a planned week meets, misses, or cannot meet with the recipes there are.

For every target and scope of the plan (a day, for a daily target):
  met         the plan's total is inside the range;
  missed      it is not, though some way of filling the open slots could have been;
  impossible  no way of filling them could be: even the richest recipe in every open
              slot (with the fixed entries and the baseline) stays under the minimum,
              or even the leanest stays over the maximum;
  unknown     some entry or the baseline has no figure, so the total is not known.
"Impossible" is claimed only when it is certain: an open slot that a recipe with no
figure could fill makes a scope's reach unbounded, and nothing is concluded.

Alongside, the recipes richest in a nutrient the plan falls short of (or leanest in
one it overshoots), which is where to look when choosing recipes to add.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mealplanner.planning.evaluate import (
    Evaluation, basic_reason, baseline_in, group_states, ineligible_reason, intake, meal_type_reason, resolve,
    slot_eaten,
)
from mealplanner.planning.model import PlanningProblem, Target


@dataclass
class Standing:
    target: Target
    met: int = 0
    missed: int = 0
    impossible: int = 0
    unknown: int = 0
    totals: list = field(default_factory=list)       # the plan's total per scope, None where unknown
    reach: list = field(default_factory=list)        # (least, most) any plan could reach, per impossible scope

    @property
    def scopes(self) -> int:
        return self.met + self.missed + self.impossible + self.unknown


def _could_fill(problem: PlanningProblem, i: int):
    """Every recipe that could fill open slot i, fresh or as leftovers."""
    for c in problem.candidates.values():
        if ineligible_reason(problem, i, c) is None:
            yield c
        elif c.leftover_days is not None and meal_type_reason(problem, i, c) is None and basic_reason(problem, c) is None:
            yield c


def slot_reach(problem: PlanningProblem, i: int, nutrient: str) -> tuple[float, float] | None:
    """(least, most) of `nutrient` open slot i could take in; None if a recipe with
    no figure could fill it (then nothing can be concluded), or if nothing can."""
    eaten = slot_eaten(problem, i)
    amounts = []
    for c in _could_fill(problem, i):
        amount = c.nutrients.get(nutrient)
        if amount is None:
            return None
        amounts.append(amount * eaten)
    return (min(amounts), max(amounts)) if amounts else None


def _in_range(total: float, t: Target) -> bool:
    return (t.minimum is None or total >= t.minimum - 1e-9) and (t.maximum is None or total <= t.maximum + 1e-9)


def standings(problem: PlanningProblem, evaluation: Evaluation) -> list[Standing]:
    resolved, _ = resolve(problem, list(evaluation.picks))
    out: dict[str, Standing] = {}
    for g in group_states(problem, resolved):
        t = g.target
        s = out.setdefault(t.name, Standing(t))
        if g.unknown:
            s.unknown += 1
            s.totals.append(None)
            continue
        s.totals.append(g.total)
        if _in_range(g.total, t):
            s.met += 1
            continue
        least = most = baseline_in(problem, t, g.slots)[0]
        bounded = True
        for i in g.slots:
            if problem.slots[i].fixed is not None:
                value = intake(problem, resolved[i], t.nutrient) or 0.0
                least, most = least + value, most + value
                continue
            r = slot_reach(problem, i, t.nutrient)
            if r is None:
                bounded = False
                break
            least, most = least + r[0], most + r[1]
        if bounded and ((t.minimum is not None and most < t.minimum - 1e-9) or (t.maximum is not None and least > t.maximum + 1e-9)):
            s.impossible += 1
            s.reach.append((least, most))
        else:
            s.missed += 1
    return list(out.values())


def richest(problem: PlanningProblem, nutrient: str, *, lowest: bool = False, n: int = 3) -> list[tuple[str, float]]:
    """The recipes with the most (or least) of a nutrient per serving."""
    known = [(c.name, c.nutrients[nutrient]) for c in problem.candidates.values()
             if c.nutrients.get(nutrient) is not None and not c.hard_excluded]
    return sorted(known, key=lambda kv: (kv[1] if lowest else -kv[1], kv[0]))[:n]


def num(x: float) -> str:
    """A figure as a person would write it: 1890, 35, 7.13, 0.868."""
    if abs(x) >= 100:
        return f"{x:,.0f}"
    return f"{x:.3g}" if abs(x) >= 1 else f"{x:.2g}"


def _range_text(t: Target, unit: str) -> str:
    if t.minimum is not None and t.maximum is not None:
        return f"{num(t.minimum)}-{num(t.maximum)} {unit}"
    return f"at least {num(t.minimum)} {unit}" if t.minimum is not None else f"at most {num(t.maximum)} {unit}"


def describe_nutrients(problem: PlanningProblem, evaluation: Evaluation) -> str:
    """The report in words: first what cannot be met, then what the plan misses, then the rest in a line."""
    units = problem.units
    rows = standings(problem, evaluation)
    lines, met_all, unknown_all = [], [], []
    order = sorted(rows, key=lambda s: (-s.impossible, -(s.missed + s.impossible), s.target.nutrient_name))
    for s in order:
        t, unit = s.target, units.get(s.target.nutrient, "")
        label = t.nutrient_name or t.name
        if s.unknown == s.scopes:
            unknown_all.append(label)
            continue
        if s.met == s.scopes - s.unknown:
            met_all.append(label)
            continue
        scope = {"daily": "days", "weekly": "weeks", "per_meal": "meals"}.get(t.scope, "scopes")
        text = f"  {label} ({'hard' if t.hard else 'soft'}, {_range_text(t, unit)} {t.scope}): met on {s.met} of {s.scopes} {scope}"
        if s.impossible:
            short = t.minimum is not None and any(most < t.minimum for _, most in s.reach)
            best = max(most for _, most in s.reach) if short else min(least for least, _ in s.reach)
            text += (f"; impossible on {s.impossible}, where the recipes can reach at most {num(best)} {unit}" if short
                     else f"; impossible on {s.impossible}, where the recipes cannot go under {num(best)} {unit}")
        known = [x for x in s.totals if x is not None]
        if known:
            text += f" (this plan: {num(min(known))}-{num(max(known))} {unit})"
        over = t.maximum is not None and known and max(known) > t.maximum
        picks = richest(problem, t.nutrient, lowest=bool(over and not (t.minimum is not None and min(known) < t.minimum)))
        if picks:
            text += ("\n      leanest per serving: " if over else "\n      richest per serving: ") + ", ".join(
                f"{name} {num(amount)} {unit}".rstrip() for name, amount in picks)
        lines.append(text)
    out = ["Nutrients:"] + (lines or ["  every target is met on every day"])
    if met_all:
        out.append("  met every time: " + ", ".join(met_all))
    if unknown_all:
        out.append("  not known (a recipe or the baseline has no figure): " + ", ".join(unknown_all))
    return "\n".join(out)
