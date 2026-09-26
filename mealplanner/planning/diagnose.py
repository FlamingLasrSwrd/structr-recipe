"""What to say when no plan satisfies the hard constraints (docs/optimizer-design.md Sec 4.7).

"No plan" is an answer, and a useful one only if it says why and what would
change it. The diagnosis reports:

  - the closest plan: the one with the smallest total violation of the hard
    targets (relaxed search), and by how much each is missed;
  - constraints that no plan could meet even on their own (the best possible pick
    in every open slot still falls short, or the fixed entries alone break them);
  - the recipes that would close a shortfall, and the ones that would have but
    are blocked because their figure is placeholder or unmarked;
  - recipes left out of every slot for a reason the owner can act on.

This is also the standalone "shortfall report with remedies" the owner was
offered: it comes out of the same run, so it cannot disagree with the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mealplanner.planning.evaluate import (
    Evaluation, Violation, basic_reason, group_states, group_violation, initial_partial, resolve,
)
from mealplanner.planning.model import PlanningProblem
from mealplanner.planning.search import auto


@dataclass
class Diagnosis:
    feasible: bool
    closest: Evaluation | None
    proven: bool                                  # the verdict covers every possible plan
    violations: list = field(default_factory=list)
    impossible_alone: list = field(default_factory=list)
    remedies: list = field(default_factory=list)
    unusable_recipes: dict = field(default_factory=dict)

    def summary(self) -> str:
        if self.feasible:
            return "A plan meeting every hard constraint exists."
        lines = ["No plan meets every hard constraint" + ("." if self.proven else " (search limit reached: not proven).")]
        for text in self.impossible_alone:
            lines.append(f"  impossible on its own: {text}")
        if self.closest is not None:
            lines.append("  closest plan misses:")
            for v in self.violations:
                lines.append("    " + describe_violation(v))
        for text in self.remedies:
            lines.append(f"  would help: {text}")
        for name, reason in sorted(self.unusable_recipes.items()):
            lines.append(f"  left out: {name}: {reason}")
        return "\n".join(lines)


def describe_violation(v: Violation) -> str:
    where = f"{v.target} on {v.group}"
    if v.kind == "below_min":
        return f"{where}: {v.total:g} against a minimum of {v.bound:g} ({v.bound - v.total:g} short)"
    if v.kind == "above_max":
        return f"{where}: {v.total:g} against a maximum of {v.bound:g} ({v.total - v.bound:g} over)"
    return f"{where}: cannot be certified, an entry has no {v.nutrient} figure"


def _impossible_alone(problem: PlanningProblem) -> list[str]:
    """Hard target groups that fail before the planner decides anything, or whose best
    case still falls short. The bounds are optimistic, so a group listed here is
    genuinely out of reach; a group not listed may still be jointly infeasible."""
    resolved, _ = resolve(problem, initial_partial(problem))
    out = []
    for g in group_states(problem, resolved):
        if not g.target.hard:
            continue
        t = g.target
        label = f"{t.name} on {g.label}"
        if g.unassigned == 0:
            kind, _, bound = group_violation(g)
            if kind:
                out.append(f"{label}: the entries already fixed for it {'break it' if kind != 'unverifiable' else 'cannot be certified'}")
            continue
        kind, _, bound = group_violation(g)
        if kind == "below_min":
            out.append(f"{label}: even the best possible pick in every open slot reaches {g.total + g.gain:g} against a minimum of {t.minimum:g}")
        elif kind == "above_max":
            out.append(f"{label}: the entries already fixed for it exceed the maximum of {t.maximum:g}")
    return out


def _remedies(problem: PlanningProblem, violations: list[Violation]) -> list[str]:
    out = []
    seen = set()
    for v in violations:
        if v.kind != "below_min":
            continue
        nutrient = next((t.nutrient for t in problem.targets if t.name == v.target), None)
        if nutrient is None or nutrient in seen:
            continue
        seen.add(nutrient)
        usable, blocked = [], []
        for c in problem.candidates.values():
            amount = c.nutrients.get(nutrient)
            if amount is None:
                continue
            (usable if basic_reason(problem, c) is None else blocked).append((amount, c))
        usable.sort(key=lambda item: (-item[0], item[1].name))
        blocked.sort(key=lambda item: (-item[0], item[1].name))
        if usable:
            best = ", ".join(f"{c.name} ({a:g} per serving)" for a, c in usable[:3])
            out.append(f"more {v.nutrient} per serving: {best}")
        for amount, c in blocked[:3]:
            if not usable or amount > usable[0][0]:
                out.append(f"{c.name} would give {amount:g} per serving but cannot be used: {basic_reason(problem, c)}")
    return out


def diagnose(problem: PlanningProblem, *, node_limit: int = 200_000, time_limit_s: float = 10.0) -> Diagnosis:
    strict = auto(problem, node_limit=node_limit, time_limit_s=time_limit_s)
    unusable = {c.name: basic_reason(problem, c) for c in problem.candidates.values() if basic_reason(problem, c)}
    if strict.best is not None:
        return Diagnosis(True, strict.best, strict.proven, [], [], [], unusable)
    relaxed = auto(problem, relaxed=True, node_limit=node_limit, time_limit_s=time_limit_s)
    violations = relaxed.best.violations if relaxed.best else []
    return Diagnosis(
        False, relaxed.best, strict.proven, violations, _impossible_alone(problem),
        _remedies(problem, violations), unusable,
    )
