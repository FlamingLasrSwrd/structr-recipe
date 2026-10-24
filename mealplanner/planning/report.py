"""A plan in words: what goes in each slot and why it scored as it did."""

from __future__ import annotations

from datetime import timedelta

from mealplanner.planning.evaluate import Evaluation
from mealplanner.planning.model import PlanningProblem


def _eats(detail: dict, problem: PlanningProblem | None = None) -> str:
    shares = detail.get("shares")
    if shares and problem is not None and problem.eaters:
        return ", eat " + ", ".join(f"{servings:g} {problem.eater_label(e)}" for e, servings in shares.items())
    eaten = detail.get("eaten", 1.0)
    return "" if abs(eaten - 1.0) < 1e-9 else f", eat {eaten:g}"


def _ahead(problem: PlanningProblem, pick, slot) -> str:
    candidate = problem.candidates.get(pick.candidate)
    if candidate is None or not candidate.ahead_hours:
        return ""
    start = (slot.start - timedelta(hours=candidate.ahead_hours)).strftime("%a %H:%M")
    return f"; made ahead: start it by {start} ({candidate.ahead_hours:g} h before)"


def describe_plan(problem: PlanningProblem, evaluation: Evaluation) -> str:
    lines = []
    details = {d["slot"]: d for d in evaluation.slot_details}
    for slot, pick in zip(problem.slots, evaluation.picks):
        when = slot.start.strftime("%a %d %b %H:%M")
        if slot.fixed is not None:
            lines.append(f"  {when}  {slot.key}: (already planned) {slot.fixed.name or slot.key}")
            continue
        d = details.get(slot.key)
        if d is None:
            lines.append(f"  {when}  {slot.key}: (unresolved)")
        elif d["kind"] == "leftover":
            lines.append(f"  {when}  {slot.key}: leftover {d['recipe']} from {d['source']}{_eats(d, problem)}")
        else:
            servings = d["cooked_servings"]
            made = f"made at {d['prep']}: {d['recipe']}" if d.get("prep") else f"cook {d['recipe']}"
            lines.append(f"  {when}  {slot.key}: {made} for {servings:g} serving{'s' if servings != 1 else ''}"
                         f"{_eats(d, problem)}{'' if d.get('prep') else _ahead(problem, pick, slot)}")
    minutes = sum(problem.candidates[p.candidate].minutes or 0.0 for s, p in zip(problem.slots, evaluation.picks)
                  if s.fixed is None and p.candidate is not None)
    lines.append(f"  cooking this week: {int(minutes // 60)} h {int(minutes % 60):02d} min of work"
                 + (f" (weighed at {problem.weights.cooking_time:g} a point an hour)" if problem.weights.cooking_time else ""))
    terms = ", ".join(f"{name} {value:+.3f}" for name, value in evaluation.terms.items() if abs(value) > 1e-12)
    lines.append(f"  score {evaluation.objective:.3f} ({terms or 'no weighted terms'})")
    return "\n".join(lines)
